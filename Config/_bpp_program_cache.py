import os
import sqlite3
import tempfile
import threading
import time

try:
	from Config._db import Database
except ModuleNotFoundError:
	from _db import Database


PROGRAM_TABLE = "b++2programs"
PROGRAM_COLUMNS = ["name", "program", "author", "uses", "created", "lastused"]
PROGRAM_CACHE_ENV = "BRAIN_BPP_PROGRAM_CACHE_PATH"
DEFAULT_PROGRAM_CACHE_PATH = os.path.join(tempfile.gettempdir(), "thebrain_bpp_program_cache.sqlite3")


def _program_cache_path():
	return os.environ.get(PROGRAM_CACHE_ENV, DEFAULT_PROGRAM_CACHE_PATH)


class BrainProgramCache:
	def __init__(self, path=None, db=None):
		self._path = path or _program_cache_path()
		self._db = db or Database()
		self._ensure_cache()
		_schedule_program_cache_flush()

	def _connect(self):
		cache_dir = os.path.dirname(self._path)
		if cache_dir:
			os.makedirs(cache_dir, exist_ok=True)
		return sqlite3.connect(self._path, timeout=30)

	def _ensure_cache(self):
		with self._connect() as cache:
			cache.execute(
				"""
				CREATE TABLE IF NOT EXISTS programs (
					name TEXT PRIMARY KEY,
					program TEXT NOT NULL,
					author TEXT NOT NULL,
					uses INTEGER NOT NULL,
					created REAL NOT NULL,
					lastused REAL NOT NULL,
					dirty INTEGER NOT NULL DEFAULT 0,
					deleted INTEGER NOT NULL DEFAULT 0,
					updated_at REAL NOT NULL
				)
				"""
			)
			cache.execute(
				"""
				CREATE TABLE IF NOT EXISTS metadata (
					key TEXT PRIMARY KEY,
					value TEXT NOT NULL
				)
				"""
			)

	def _metadata(self, key):
		with self._connect() as cache:
			row = cache.execute("SELECT value FROM metadata WHERE key = ?", (key,)).fetchone()
		return None if row is None else row[0]

	def _set_metadata(self, key, value):
		with self._connect() as cache:
			cache.execute(
				"""
				INSERT INTO metadata (key, value) VALUES (?, ?)
				ON CONFLICT(key) DO UPDATE SET value = excluded.value
				""",
				(key, str(value))
			)

	def _row_from_cache(self, row):
		if row is None:
			return None
		name, program, author, uses, created, lastused = row
		return (name, program, author, int(uses), float(created), float(lastused))

	def _cache_row(self, row, dirty=False, deleted=False):
		name, program, author, uses, created, lastused = row
		with self._connect() as cache:
			cache.execute(
				"""
				INSERT INTO programs (name, program, author, uses, created, lastused, dirty, deleted, updated_at)
				VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
				ON CONFLICT(name) DO UPDATE SET
					program = excluded.program,
					author = excluded.author,
					uses = excluded.uses,
					created = excluded.created,
					lastused = excluded.lastused,
					dirty = excluded.dirty,
					deleted = excluded.deleted,
					updated_at = excluded.updated_at
				""",
				(
					str(name),
					str(program),
					str(author),
					int(uses),
					float(created),
					float(lastused),
					int(dirty),
					int(deleted),
					time.time(),
				)
			)

	def _cache_rows_from_database(self, rows):
		with self._connect() as cache:
			cache.execute("DELETE FROM programs WHERE dirty = 0")
			for row in rows:
				name, program, author, uses, created, lastused = row
				existing = cache.execute(
					"SELECT dirty FROM programs WHERE name = ?",
					(name,)
				).fetchone()
				if existing is not None and existing[0]:
					continue
				cache.execute(
					"""
					INSERT INTO programs (name, program, author, uses, created, lastused, dirty, deleted, updated_at)
					VALUES (?, ?, ?, ?, ?, ?, 0, 0, ?)
					ON CONFLICT(name) DO UPDATE SET
						program = excluded.program,
						author = excluded.author,
						uses = excluded.uses,
						created = excluded.created,
						lastused = excluded.lastused,
						deleted = 0,
						updated_at = excluded.updated_at
					""",
					(str(name), str(program), str(author), int(uses), float(created), float(lastused), time.time())
				)
		self._set_metadata("full_load_complete", "1")

	def _cached_programs(self):
		with self._connect() as cache:
			rows = cache.execute(
				"""
				SELECT name, program, author, uses, created, lastused
				FROM programs
				WHERE deleted = 0
				"""
			).fetchall()
		return [self._row_from_cache(row) for row in rows]

	def list_programs(self):
		if self._metadata("full_load_complete") != "1":
			try:
				rows = self._db.get_entries(PROGRAM_TABLE, columns=PROGRAM_COLUMNS)
			except Exception:
				return self._cached_programs()
			self._cache_rows_from_database(rows)

		return self._cached_programs()

	def get_program(self, name):
		with self._connect() as cache:
			row = cache.execute(
				"""
				SELECT name, program, author, uses, created, lastused, deleted
				FROM programs
				WHERE name = ?
				""",
				(name,)
			).fetchone()
		if row is not None:
			if row[6]:
				return None
			return self._row_from_cache(row[:6])

		try:
			rows = self._db.get_entries(PROGRAM_TABLE, columns=PROGRAM_COLUMNS, conditions={"name": name})
		except Exception:
			return None

		if len(rows) == 0:
			return None

		self._cache_row(rows[0])
		return self._row_from_cache(rows[0])

	def create_program(self, name, program, author):
		row = (name, program, str(author), 0, time.time(), 0)
		self._cache_row(row, dirty=True)
		_schedule_program_cache_flush()
		return row

	def edit_program(self, name, program):
		row = self.get_program(name)
		if row is None:
			return None

		updated = (row[0], program, row[2], row[3], row[4], row[5])
		self._cache_row(updated, dirty=True)
		_schedule_program_cache_flush()
		return updated

	def delete_program(self, name):
		row = self.get_program(name)
		if row is None:
			return False

		self._cache_row(row, dirty=True, deleted=True)
		_schedule_program_cache_flush()
		return True

	def increment_uses(self, name):
		row = self.get_program(name)
		if row is None:
			return None

		updated = (row[0], row[1], row[2], row[3] + 1, row[4], time.time())
		self._cache_row(updated, dirty=True)
		_schedule_program_cache_flush()
		return updated

	def flush(self):
		with self._connect() as cache:
			rows = cache.execute(
				"""
				SELECT name, program, author, uses, created, lastused, deleted
				FROM programs
				WHERE dirty = 1
				ORDER BY updated_at
				"""
			).fetchall()

		for name, program, author, uses, created, lastused, deleted in rows:
			try:
				if deleted:
					self._db.remove_entry(PROGRAM_TABLE, conditions={"name": name})
					with self._connect() as cache:
						cache.execute("DELETE FROM programs WHERE name = ?", (name,))
					continue

				existing = self._db.get_entries(PROGRAM_TABLE, columns=["name"], conditions={"name": name})
				if len(existing) == 0:
					self._db.add_entry(PROGRAM_TABLE, [name, program, author, uses, created, lastused])
				else:
					self._db.edit_entry(
						PROGRAM_TABLE,
						entry={"program": program, "uses": uses, "lastused": lastused},
						conditions={"name": name}
					)
			except Exception:
				continue

			with self._connect() as cache:
				cache.execute(
					"UPDATE programs SET dirty = 0, updated_at = ? WHERE name = ?",
					(time.time(), name)
				)


_program_flush_thread = None
_program_flush_thread_lock = threading.Lock()


def _flush_program_cache_to_database():
	BrainProgramCache().flush()


def _schedule_program_cache_flush():
	global _program_flush_thread

	with _program_flush_thread_lock:
		if _program_flush_thread is not None and _program_flush_thread.is_alive():
			return

		_program_flush_thread = threading.Thread(target=_flush_program_cache_to_database, daemon=True)
		_program_flush_thread.start()
