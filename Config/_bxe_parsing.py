import re
import os
import sqlite3
import tempfile
import threading
import time
from contextlib import contextmanager
from typing import Any

try:
	import fcntl
except ImportError:
	fcntl = None

try:
	from Config._db import Database
	from Config._bpp_parsing import undo_str_array, str_array
except ModuleNotFoundError:
	from _db import Database
	from _bpp_parsing import undo_str_array, str_array

from bxengine.tokenizer.tokenize import Tokenizer, TokenizationResult
from bxengine.parsing.parser import Parser, ParsingResult
from bxengine.parsing.nodes import Nodes
from bxengine.runtime.executor import Executor, ExecutorResult
from bxengine.runtime.extensions.builtin import BuiltinExtension
from bxengine.runtime.extensions.BxeExtension import (
	BxeStatefulExtension,
	bpp_function,
	BxeRuntimeSyntaxException,
)
from bxengine.exceptions import ProgramDefinedException


_GLOBAL_VARIABLE_TABLE = "b++2variables"
_GLOBAL_VARIABLE_COLUMNS = ["name", "value", "type", "owner"]
_GLOBAL_CACHE_ENV = "BRAIN_BXE_GLOBAL_CACHE_PATH"
_DEFAULT_GLOBAL_CACHE_PATH = os.path.join(tempfile.gettempdir(), "thebrain_bxe_global_cache.sqlite3")

_USER_VARIABLE_TABLE = "b++2uservars"
_USER_VARIABLE_COLUMNS = ["name", "value", "type", "owner"]
_USER_CACHE_ENV = "BRAIN_BXE_USER_CACHE_PATH"
_DEFAULT_USER_CACHE_PATH = os.path.join(tempfile.gettempdir(), "thebrain_bxe_user_cache.sqlite3")

def _var_type(value):
	type_list = [int, float, str, list]
	for t in type_list:
		if type(value) == t:
			return type_list.index(t)
	raise TypeError(f"Value {value} could not be attributed to any valid data type")


def _decode_global_value(value, value_type):
	type_list = [int, float, str, list]
	if type_list[value_type] == list:
		return undo_str_array(value)
	return type_list[value_type](value)


def _encode_global_value(value):
	if type(value) == list:
		return str_array(value)
	return str(value)


def _global_cache_path():
	return os.environ.get(_GLOBAL_CACHE_ENV, _DEFAULT_GLOBAL_CACHE_PATH)

def _global_cache_lock_path():
	return f"{_global_cache_path()}.lock"
	
@contextmanager
def _bxe_global_execution_lock():
	lock_path = _global_cache_lock_path()
	lock_dir = os.path.dirname(lock_path)
	if lock_dir:
		os.makedirs(lock_dir, exist_ok=True)

	with open(lock_path, "a") as lock_file:
		if fcntl is not None:
			fcntl.flock(lock_file, fcntl.LOCK_EX)

		try:
			yield
		finally:
			if fcntl is not None:
				fcntl.flock(lock_file, fcntl.LOCK_UN)


class _BrainGlobalCache:
	def __init__(self, path=None):
		self._path = path or _global_cache_path()
		self._ensure_cache()

	def _connect(self):
		cache_dir = os.path.dirname(self._path)
		if cache_dir:
			os.makedirs(cache_dir, exist_ok=True)
		return sqlite3.connect(self._path, timeout=30)

	def _ensure_cache(self):
		with self._connect() as cache:
			cache.execute(
				"""
				CREATE TABLE IF NOT EXISTS variables (
					name TEXT PRIMARY KEY,
					value TEXT NOT NULL,
					type INTEGER NOT NULL,
					owner TEXT NOT NULL,
					dirty INTEGER NOT NULL DEFAULT 0,
					updated_at REAL NOT NULL
				)
				"""
			)

	def get(self, name):
		with self._connect() as cache:
			row = cache.execute(
				"SELECT name, value, type, owner, dirty FROM variables WHERE name = ?",
				(name,)
			).fetchone()
		return row

	def get_many(self, names):
		if len(names) == 0:
			return {}

		placeholders = ", ".join(["?"] * len(names))
		with self._connect() as cache:
			rows = cache.execute(
				f"SELECT name, value, type, owner, dirty FROM variables WHERE name IN ({placeholders})",
				list(names)
			).fetchall()
		return {row[0]: row for row in rows}

	def dirty_entries(self):
		with self._connect() as cache:
			return cache.execute(
				"SELECT name, value, type, owner, dirty FROM variables WHERE dirty = 1"
			).fetchall()

	def upsert(self, name, value, value_type, owner, dirty):
		with self._connect() as cache:
			cache.execute(
				"""
				INSERT INTO variables (name, value, type, owner, dirty, updated_at)
				VALUES (?, ?, ?, ?, ?, ?)
				ON CONFLICT(name) DO UPDATE SET
					value = excluded.value,
					type = excluded.type,
					owner = excluded.owner,
					dirty = excluded.dirty,
					updated_at = excluded.updated_at
				""",
				(name, str(value), int(value_type), str(owner), int(dirty), time.time())
			)

	def mark_clean(self, name):
		with self._connect() as cache:
			cache.execute(
				"UPDATE variables SET dirty = 0, updated_at = ? WHERE name = ?",
				(time.time(), name)
			)

	def refresh_from_database_rows(self, rows):
		with self._connect() as cache:
			for name, value, value_type, owner in rows:
				existing = cache.execute(
					"SELECT dirty FROM variables WHERE name = ?",
					(name,)
				).fetchone()
				if existing is not None and existing[0]:
					continue

				cache.execute(
					"""
					INSERT INTO variables (name, value, type, owner, dirty, updated_at)
					VALUES (?, ?, ?, ?, 0, ?)
					ON CONFLICT(name) DO UPDATE SET
						value = excluded.value,
						type = excluded.type,
						owner = excluded.owner,
						dirty = 0,
						updated_at = excluded.updated_at
					""",
					(name, str(value), int(value_type), str(owner), time.time())
				)


_global_flush_thread = None
_global_flush_thread_lock = threading.Lock()


def _flush_global_cache_to_database():
	cache = _BrainGlobalCache()
	db = Database()

	for v_name, v_value, v_type, v_owner, _dirty in cache.dirty_entries():
		try:
			v_list = db.get_entries(
				_GLOBAL_VARIABLE_TABLE,
				columns=_GLOBAL_VARIABLE_COLUMNS,
				conditions={"name": v_name}
			)

			if len(v_list) == 0:
				db.add_entry(_GLOBAL_VARIABLE_TABLE, [v_name, v_value, v_type, v_owner])
			else:
				v_db_owner = str(v_list[0][3])
				if v_db_owner != str(v_owner):
					continue

				db.edit_entry(
					_GLOBAL_VARIABLE_TABLE,
					entry={"value": v_value, "type": v_type},
					conditions={"name": v_name}
				)
		except Exception:
			continue

		cache.mark_clean(v_name)


def _schedule_global_cache_flush():
	global _global_flush_thread

	with _global_flush_thread_lock:
		if _global_flush_thread is not None and _global_flush_thread.is_alive():
			return

		_global_flush_thread = threading.Thread(target=_flush_global_cache_to_database, daemon=True)
		_global_flush_thread.start()



def _user_cache_path():
	return os.environ.get(_USER_CACHE_ENV, _DEFAULT_USER_CACHE_PATH)

def _global_cache_lock_path():
	return f"{_user_cache_path()}.lock"
	
@contextmanager
def _bxe_user_execution_lock():
	lock_path = _user_cache_lock_path()
	lock_dir = os.path.dirname(lock_path)
	if lock_dir:
		os.makedirs(lock_dir, exist_ok=True)

	with open(lock_path, "a") as lock_file:
		if fcntl is not None:
			fcntl.flock(lock_file, fcntl.LOCK_EX)

		try:
			yield
		finally:
			if fcntl is not None:
				fcntl.flock(lock_file, fcntl.LOCK_UN)


class _BrainUserCache:
	def __init__(self, path=None):
		self._path = path or _user_cache_path()
		self._ensure_cache()

	def _connect(self):
		cache_dir = os.path.dirname(self._path)
		if cache_dir:
			os.makedirs(cache_dir, exist_ok=True)
		return sqlite3.connect(self._path, timeout=30)

	def _ensure_cache(self):
		with self._connect() as cache:
			cache.execute(
				"""
				CREATE TABLE IF NOT EXISTS variables (
					name TEXT PRIMARY KEY,
					value TEXT NOT NULL,
					type INTEGER NOT NULL,
					owner TEXT NOT NULL,
					dirty INTEGER NOT NULL DEFAULT 0,
					updated_at REAL NOT NULL
				)
				"""
			)

	def get(self, name, user):
		with self._connect() as cache:
			row = cache.execute(
				"SELECT name, value, type, owner, dirty FROM variables WHERE name = ?",
				(str(name)+":"+str(user),)
			).fetchone()
		return row

	def get_many(self, names, user):
		if len(names) == 0:
			return {}

		placeholders = ", ".join(["?:"+str(user)] * len(names))
		with self._connect() as cache:
			rows = cache.execute(
				f"SELECT name, value, type, owner, dirty FROM variables WHERE name IN ({placeholders})",
				list(names)
			).fetchall()
		return {row[0]: row for row in rows}

	def dirty_entries(self):
		with self._connect() as cache:
			return cache.execute(
				"SELECT name, value, type, owner, dirty FROM variables WHERE dirty = 1"
			).fetchall()

	def upsert(self, name, user, value, value_type, owner, dirty):
		with self._connect() as cache:
			cache.execute(
				"""
				INSERT INTO variables (name, value, type, owner, dirty, updated_at)
				VALUES (?, ?, ?, ?, ?, ?)
				ON CONFLICT(name) DO UPDATE SET
					value = excluded.value,
					type = excluded.type,
					owner = excluded.owner,
					dirty = excluded.dirty,
					updated_at = excluded.updated_at
				""",
				(str(name)+":"+str(user), str(value), int(value_type), str(owner), int(dirty), time.time())
			)

	def mark_clean(self, name):
		with self._connect() as cache:
			cache.execute(
				"UPDATE variables SET dirty = 0, updated_at = ? WHERE name = ?",
				(time.time(), name)
			)

	def refresh_from_database_rows(self, rows):
		with self._connect() as cache:
			for name, value, value_type, owner in rows:
				existing = cache.execute(
					"SELECT dirty FROM variables WHERE name = ?",
					(name,)
				).fetchone()
				if existing is not None and existing[0]:
					continue

				cache.execute(
					"""
					INSERT INTO variables (name, value, type, owner, dirty, updated_at)
					VALUES (?, ?, ?, ?, 0, ?)
					ON CONFLICT(name) DO UPDATE SET
						value = excluded.value,
						type = excluded.type,
						owner = excluded.owner,
						dirty = 0,
						updated_at = excluded.updated_at
					""",
					(name, str(value), int(value_type), str(owner), time.time())
				)


_user_flush_thread = None
_user_flush_thread_lock = threading.Lock()


def _flush_user_cache_to_database():
	cache = _BrainUserCache()
	db = Database()

	for v_name, v_value, v_type, v_owner, _dirty in cache.dirty_entries():
		try:
			v_list = db.get_entries(
				_USER_VARIABLE_TABLE,
				columns=_USER_VARIABLE_COLUMNS,
				conditions={"name": v_name}
			)

			if len(v_list) == 0:
				db.add_entry(_USER_VARIABLE_TABLE, [v_name, v_value, v_type, v_owner])
			else:
				v_db_owner = str(v_list[0][3])
				if v_db_owner != str(v_owner):
					continue

				db.edit_entry(
					_USER_VARIABLE_TABLE,
					entry={"value": v_value, "type": v_type},
					conditions={"name": v_name}
				)
		except Exception:
			continue

		cache.mark_clean(v_name)


def _schedule_user_cache_flush():
	global _user_flush_thread

	with _user_flush_thread_lock:
		if _user_flush_thread is not None and _user_flush_thread.is_alive():
			return

		_user_flush_thread = threading.Thread(target=_flush_user_cache_to_database, daemon=True)
		_user_flush_thread.start()


class BrainDiscordExtension(BxeStatefulExtension):
	def __init__(self, runner, channel):
		self._runner = runner
		self._channel = channel
		self.buttons = []

	@bpp_function()
	def USERNAME(self):
		return self._runner.name

	@bpp_function()
	def USERID(self):
		return self._runner.id

	@bpp_function()
	def CHANNEL(self):
		return self._channel.id

	@bpp_function()
	def BUTTON(self, *args):
		self.buttons.append([str(a) for a in args])
		return ""


class BrainGlobalExtension(BxeStatefulExtension):
	def __init__(self, author):
		self._author = str(author)
		self._db = Database()
		self._cache = _BrainGlobalCache()
		_schedule_global_cache_flush()
		self.global_variables = {}
		self._changed = set()

	def post_parse_hook(self, nodes):
		names = self._collect_trivial_global_var_reads(nodes)
		if len(names) == 0:
			return

		rows_by_name = self._cache.get_many(names)
		missing_names = names - set(rows_by_name.keys())

		for missing_name in missing_names:
			try:
				v_list = self._db.get_entries(
					_GLOBAL_VARIABLE_TABLE,
					columns=_GLOBAL_VARIABLE_COLUMNS,
					conditions={"name": missing_name}
				)
			except Exception:
				continue

			if len(v_list) == 0:
				continue

			self._cache.refresh_from_database_rows(v_list)
			rows_by_name[missing_name] = v_list[0]

		for v_name in names:
			row = rows_by_name.get(v_name)
			if row is None:
				continue

			(_, v_value, v_type, *_rest) = row
			self.global_variables[v_name] = _decode_global_value(v_value, v_type)

	@staticmethod
	def _collect_trivial_global_var_reads(nodes):
		names = set()
		stack = list(nodes)

		while len(stack) != 0:
			node = stack.pop()
			if isinstance(node, Nodes.Function):
				if (
					node.name.upper() == "GLOBAL"
					and len(node.arguments) == 2
					and isinstance(node.arguments[0], Nodes.StringNode)
					and isinstance(node.arguments[1], Nodes.StringNode)
					and node.arguments[0].value.lower() == "var"
				):
					names.add(node.arguments[1].value)
				stack.extend(node.arguments)

		return names

	@bpp_function("GLOBAL")
	def global_fn(self, func_type: str, variable: str, value: Any = None):
		if re.search(r"[^A-Za-z_0-9]", variable) or re.search(r"[0-9]", variable[0]):
			raise NameError(
			f"Global variable name must be only letters, underscores and numbers, and cannot start with a number")
		match str(func_type).lower():
			case "define":
				if len(str(value)) > 100_000:
					raise ValueError("Global variables are capped at 100,000 characters or fewer")
				self.global_variables[variable] = value
				self._changed.add(variable)
				return ""
			case "var":
				if value:
					raise BxeRuntimeSyntaxException("GLOBAL VAR expected 2 parameters, but got 3")
				if variable in self.global_variables.keys():
					return self.global_variables[variable]

				row = self._cache.get(variable)
				if row is not None:
					(_, v_value, v_type, _v_owner, _dirty) = row
				else:
					v_list = self._db.get_entries(
						_GLOBAL_VARIABLE_TABLE,
						columns=_GLOBAL_VARIABLE_COLUMNS,
						conditions={"name": variable}
					)
					if len(v_list) == 0:
						raise NameError(f"No global variable by the name {variable} defined")

					(_, v_value, v_type, _v_owner) = v_list[0]
					self._cache.refresh_from_database_rows(v_list)

				decoded = _decode_global_value(v_value, v_type)
				self.global_variables[variable] = decoded
				return decoded
			case _:
				raise BxeRuntimeSyntaxException("GLOBAL needs a function type parameter")

	def _flush_cached_changes(self):
		for v_name, v_value, v_type, v_owner, _dirty in self._cache.dirty_entries():
			try:
				self._write_variable_to_database(v_name, v_value, v_type, v_owner)
			except Exception:
				continue
			self._cache.mark_clean(v_name)

	def _write_variable_to_database(self, variable, value_string, value_type, owner):
		v_list = self._db.get_entries(
			_GLOBAL_VARIABLE_TABLE,
			columns=_GLOBAL_VARIABLE_COLUMNS,
			conditions={"name": variable}
		)

		if len(v_list) == 0:
			self._db.add_entry(_GLOBAL_VARIABLE_TABLE, [variable, value_string, value_type, owner])
			return

		v_owner = str(v_list[0][3])
		if v_owner != str(owner):
			raise PermissionError(
				f"Only the author of the {variable} variable can edit its value ({v_owner})"
			)

		self._db.edit_entry(
			_GLOBAL_VARIABLE_TABLE,
			entry={"value": value_string, "type": value_type},
			conditions={"name": variable}
		)

	def persist(self):
		for variable in self._changed:
			value = self.global_variables[variable]
			value_type = _var_type(value)
			value_string = _encode_global_value(value)

			cached = self._cache.get(variable)
			if cached is None:
				v_list = self._db.get_entries(
					_GLOBAL_VARIABLE_TABLE,
					columns=_GLOBAL_VARIABLE_COLUMNS,
					conditions={"name": variable}
				)
				if len(v_list) != 0:
					self._cache.refresh_from_database_rows(v_list)
					cached = self._cache.get(variable)

			if cached is not None and str(cached[3]) != self._author:
				raise PermissionError(
					f"Only the author of the {variable} variable can edit its value ({cached[3]})"
				)

			self._cache.upsert(variable, value_string, value_type, self._author, dirty=True)

		_schedule_global_cache_flush()


def _global_extension_factory(author):
	class RuntimeGlobalExtension(BrainGlobalExtension):
		def __init__(self):
			super().__init__(author)
	return RuntimeGlobalExtension


class BrainUserExtension(BxeStatefulExtension):
	def __init__(self, author, runner):
		self._author = str(author)
		self._runner_id = str(runner.id)
		self._db = Database()
		self._cache = _BrainUserCache()
		_schedule_user_cache_flush()
		self.user_variables = {}
		self._changed = set()

	def post_parse_hook(self, nodes):
		names = self._collect_trivial_user_var_reads(nodes)
		if len(names) == 0:
			return

		rows_by_name = self._cache.get_many(names, self._runner_id)
		missing_names = names - set(rows_by_name.keys())

		for missing_name in missing_names:
			name_with_id = missing_name+":"+self._runner_id
			try:
				v_list = self._db.get_entries(
					_USER_VARIABLE_TABLE,
					columns=_USER_VARIABLE_COLUMNS,
					conditions={"name": name_with_id}
				)
			except Exception:
				continue

			if len(v_list) == 0:
				continue

			self._cache.refresh_from_database_rows(v_list)
			rows_by_name[name_with_id] = v_list[0]

		for v_name in names:
			name_with_id = v_name+":"+self._runner_id
			row = rows_by_name.get(name_with_id)
			if row is None:
				continue

			(_, v_value, v_type, *_rest) = row
			self.user_variables[v_name] = _decode_global_value(v_value, v_type)

	@staticmethod
	def _collect_trivial_user_var_reads(nodes):
		names = set()
		stack = list(nodes)

		while len(stack) != 0:
			node = stack.pop()
			if isinstance(node, Nodes.Function):
				if (
					node.name.upper() == "USER"
					and len(node.arguments) == 2
					and isinstance(node.arguments[0], Nodes.StringNode)
					and isinstance(node.arguments[1], Nodes.StringNode)
					and node.arguments[0].value.lower() == "var"
				):
					names.add(node.arguments[1].value)
				stack.extend(node.arguments)

		return names

	@bpp_function("USER")
	def user_fn(self, func_type: str, variable: str, value: Any = None):
		if re.search(r"[^A-Za-z_0-9]", variable) or re.search(r"[0-9]", variable[0]):
			raise NameError(
			f"User variable name must be only letters, underscores and numbers, and cannot start with a number")

		db_name = variable + ":" + self._runner_id
		match str(func_type).lower():
			case "define":
				if len(str(value)) > 100_000:
					raise ValueError("User variables are capped at 100,000 characters or fewer")
				self.user_variables[db_name] = value
				self._changed.add(db_name)
				return ""
			case "var":
				if value:
					raise BxeRuntimeSyntaxException("USER VAR expected 2 parameters, but got 3")
				if variable in self.user_variables.keys():
					return self.user_variables[db_name]

				row = self._cache.get(variable, self._runner_id)
				if row is not None:
					(_, v_value, v_type, _v_owner, _dirty) = row
				else:
					v_list = self._db.get_entries(
						_USER_VARIABLE_TABLE,
						columns=_USER_VARIABLE_COLUMNS,
						conditions={"name": db_name}
					)
					if len(v_list) == 0:
						raise NameError(f"This user does not have {variable} defined")

					(_, v_value, v_type, _v_owner) = v_list[0]
					self._cache.refresh_from_database_rows(v_list)

				decoded = _decode_global_value(v_value, v_type)
				self.user_variables[db_name] = decoded
				return decoded
			case _:
				raise BxeRuntimeSyntaxException("USER needs a function type parameter")

	def _flush_cached_changes(self):
		for v_name, v_value, v_type, v_owner, _dirty in self._cache.dirty_entries():
			try:
				self._write_variable_to_database(v_name, v_value, v_type, v_owner)
			except Exception:
				continue
			self._cache.mark_clean(v_name)

	def _write_variable_to_database(self, variable, value_string, value_type, owner):
		v_list = self._db.get_entries(
			_USER_VARIABLE_TABLE,
			columns=_USER_VARIABLE_COLUMNS,
			patterns={"name": variable.split(":")[0]+":%"}
		)

		if len(v_list) == 0:
			self._db.add_entry(_USER_VARIABLE_TABLE, [variable, value_string, value_type, owner])
			return

		v_owner = str(v_list[0][3])
		if v_owner != str(owner):
			raise PermissionError(
				f"Only the author of the {variable} variable can edit its value ({v_owner})"
			)

		self._db.edit_entry(
			_USER_VARIABLE_TABLE,
			entry={"value": value_string, "type": value_type},
			conditions={"name": variable}
		)

	def persist(self):
		for variable in self._changed:
			value = self.user_variables[variable]
			value_type = _var_type(value)
			value_string = _encode_global_value(value)

			cached = self._cache.get(variable)
			if cached is None:
				v_list = self._db.get_entries(
					_USER_VARIABLE_TABLE,
					columns=_USER_VARIABLE_COLUMNS,
					conditions={"name": variable}
				)
				if len(v_list) != 0:
					self._cache.refresh_from_database_rows(v_list)
					cached = self._cache.get(variable)

			if cached is not None and str(cached[3]) != self._author:
				raise PermissionError(
					f"Only the author of the {variable} variable can edit its value ({cached[3]})"
				)

			self._cache.upsert(variable, value_string, value_type, self._author, dirty=True)

		_schedule_user_cache_flush()


def _user_extension_factory(author, runner):
	class RuntimeUserExtension(BrainUserExtension):
		def __init__(self):
			super().__init__(author, runner)
	return RuntimeUserExtension


def _discord_extension_factory(runner, channel):
	class RuntimeDiscordExtension(BrainDiscordExtension):
		def __init__(self):
			super().__init__(runner, channel)
	return RuntimeDiscordExtension


def _run_bxe_program_unlocked(code, p_args, author, runner, channel):
	buttons = []
	warnings = []
	try:
		tok = Tokenizer.tokenize(code)
		if isinstance(tok, TokenizationResult.Error):
			return [SyntaxError(f"{tok.message}\n\n{tok.range.debug_info()}"), buttons, warnings]
		warnings.extend(tok.warnings)

		par = Parser.parse(code, tok.tokens)
		if isinstance(par, ParsingResult.Error):
			warnings.extend(par.warnings)
			return [SyntaxError(f"{par.message}\n\n{par.range.debug_info()}"), buttons, warnings]
		warnings.extend(par.warnings)

		exe = Executor(
			extensions=[BuiltinExtension()],
			stateful_extensions=[
				_global_extension_factory(author),
				_user_extension_factory(author, runner),
				_discord_extension_factory(runner, channel),
			],
			program_args=p_args
		)

		result = exe.execute(par.nodes)
		if isinstance(result, ExecutorResult.Error):
			exc = result.exception
			span = getattr(exc, "span", None)
			if span is not None and not isinstance(exc, ProgramDefinedException):
				try:
					exc = type(exc)(f"{exc}\n\n{span.debug_info()}")
				except Exception:
					pass
			return [exc, buttons, warnings]

		for ext in result.stateful_extensions:
			if isinstance(ext, BrainGlobalExtension):
				ext.persist()
			elif isinstance(ext, BrainDiscordExtension):
				buttons = ext.buttons

		return [result.output, buttons, warnings]
	except Exception as e:
		return [e, buttons, warnings]


def run_bxe_program(code, p_args, author, runner, channel):
	buttons = []
	warnings = []
	try:
		with _bxe_global_execution_lock():
			return _run_bxe_program_unlocked(code, p_args, author, runner, channel)
	except Exception as e:
		return [e, buttons, warnings]
