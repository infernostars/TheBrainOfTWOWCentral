import discord, os, re, time, traceback, sys

from discord.ui import Button, View
from functools import partial

from Config._db import Database
from Config._bpp_parsing import undo_str_array, str_array

from bxengine.tokenizer.tokenize import Tokenizer, TokenizationResult
from bxengine.parsing.parser import Parser, ParsingResult
from bxengine.parsing.nodes import Nodes
from bxengine.runtime.executor import Executor, ExecutorResult
from bxengine.runtime.extensions.builtin import BuiltinExtension
from bxengine.runtime.extensions.BxeExtension import BxeStatefulExtension, bpp_function, BxeRuntimeSyntaxException

def HELP(PREFIX):
	return {
		"COOLDOWN": 3,
		"MAIN": "Runs B++ programs using the bxengine runtime",
		"FORMAT": "[run <code> | <program> (args)]",
		"CHANNEL": 0,
		"USAGE": f"""Use `{PREFIX}bxe run [code]` to run raw code with bxengine.
		Use `{PREFIX}bxe [program] (args)` to run an existing saved B++ program with bxengine.
		This command only executes programs; program management remains under `{PREFIX}tag`.""".replace("\n", "").replace("\t", ""),
		"CATEGORY": "Fun"
	}


PERMS = 1 # Member
ALIASES = ["BXENGINE"]
REQ = []

LATEST_BUTTONS = {}


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
		self.global_variables = {}
		self._changed = set()

	def post_parse_hook(self, nodes):
		names = self._collect_trivial_global_var_reads(nodes)
		if len(names) == 0:
			return

		v_list = self._db.get_entries("b++2variables", columns=["name", "value", "type", "owner"])
		for (v_name, v_value, v_type, _v_owner) in v_list:
			if v_name not in names:
				continue
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
	def global_fn(self, func_type, variable, value=None):
		match str(func_type).lower():
			case "define":
				self.global_variables[variable] = value
				self._changed.add(variable)
				return ""
			case "var":
				if value:
					raise BxeRuntimeSyntaxException("GLOBAL VAR expected 2 parameters, but got 3")
				if variable in self.global_variables.keys():
					return self.global_variables[variable]

				v_list = self._db.get_entries(
					"b++2variables", columns=["name", "value", "type", "owner"], conditions={"name": variable}
				)
				if len(v_list) == 0:
					raise NameError(f"No global variable by the name {variable} defined")

				(_, v_value, v_type, _v_owner) = v_list[0]
				decoded = _decode_global_value(v_value, v_type)
				self.global_variables[variable] = decoded
				return decoded
			case _:
				raise BxeRuntimeSyntaxException("GLOBAL needs a function type parameter")

	def unsaved_changes(self):
		return sorted(list(self._changed))


def _global_extension_factory(author):
	class RuntimeGlobalExtension(BrainGlobalExtension):
		def __init__(self):
			super().__init__(author)
	return RuntimeGlobalExtension


def _discord_extension_factory(runner, channel):
	class RuntimeDiscordExtension(BrainDiscordExtension):
		def __init__(self):
			super().__init__(runner, channel)
	return RuntimeDiscordExtension


def _execute_bxe(program, program_args, author, runner, channel):

	tok = Tokenizer.tokenize(program)
	if isinstance(tok, TokenizationResult.Error):
		raise SyntaxError(f"{tok.message}\n\n{tok.range.debug_info()}")

	par = Parser.parse(program, tok.tokens)
	if isinstance(par, ParsingResult.Error):
		raise SyntaxError(f"{par.message}\n\n{par.range.debug_info()}")

	exe = Executor(
		extensions=[BuiltinExtension()],
		stateful_extensions=[
			_global_extension_factory(author),
			_discord_extension_factory(runner, channel),
		],
		program_args=program_args
	)

	result = exe.execute(par.nodes)
	if isinstance(result, ExecutorResult.Error):
		exc = result.exception
		span = getattr(exc, "span", None)
		if span is not None:
			raise type(exc)(f"{exc}\n\n{span.debug_info()}")
		raise exc

	global_ext = None
	discord_ext = None
	for ext in result.stateful_extensions:
		if isinstance(ext, BrainGlobalExtension):
			global_ext = ext
		elif isinstance(ext, BrainDiscordExtension):
			discord_ext = ext

	unsaved_global_writes = []
	if global_ext is not None:
		unsaved_global_writes = global_ext.unsaved_changes()

	buttons = []
	if discord_ext is not None:
		buttons = discord_ext.buttons

	return result.output, buttons, unsaved_global_writes


async def MAIN(message, args, level, perms, SERVER):

	if message.channel.id == 598616636823437352 and perms < 2:
		return

	if level == 1:
		await message.channel.send("Include a subcommand or tag name!")
		return

	db = Database()

	if args[1].lower() == "run":
		if level > 2:
			program = " ".join(args[2:])
		elif len(message.attachments) != 0:
			try:
				if message.attachments[0].size >= 60000:
					await message.channel.send("Your program must be under **60KB**.")
					return
				await message.attachments[0].save(f"Config/{message.id}.txt")
			except Exception:
				await message.channel.send("Include a valid program to run!")
				return
			program = open(f"Config/{message.id}.txt", "r", encoding="utf-8").read()
			os.remove(f"Config/{message.id}.txt")
		else:
			await message.channel.send("Include a valid program to run!")
			return

		while program.startswith("`") and program.endswith("`"):
			program = program[1:-1]
		program = program.replace("{}", "\v")

		program_args = []
		author = message.author.id
		runner = message.author
	else:
		tag_name = args[1]
		if tag_name in ["create", "edit", "delete", "info", "tags"]:
			await message.channel.send(f"For the time being, tag modification must be done with tc/tag and not tc/bxe.")
			return

		tag_list = db.get_entries("b++2programs", columns=["name", "program", "author", "uses"])
		if tag_name not in [x[0] for x in tag_list]:
			await message.channel.send(f"There's no program under the name `{tag_name}`!")
			return

		tag_info = [x for x in tag_list if x[0] == tag_name][0]
		program = tag_info[1]

		uses = tag_info[3] + 1
		db.edit_entry("b++2programs", entry={"uses": uses, "lastused": time.time()}, conditions={"name": tag_name})

		program_args = args[2:]
		author = tag_info[2]
		runner = message.author

	async def evaluate_and_send(program, program_args, author, runner, source_message, is_button=False):
		try:
			program_output, buttons, unsaved_global_writes = _execute_bxe(program, program_args, author, runner, source_message.channel)
		except Exception as e:
			await source_message.channel.send(
				embed=discord.Embed(color=0xFF0000, title=f"{type(e).__name__}", description=f"```{e}```"),
				allowed_mentions=discord.AllowedMentions.none()
			)
			return

		if is_button:
			program_output = program_output.rstrip() + f"\n-# Button pressed by {runner.mention}"

		async def button_callback(program, interaction):
			try:
				custom_id = interaction.data["custom_id"]
				tag_name = custom_id.split(" ")[1]

				tag_list = db.get_entries("b++2programs", columns=["name", "program", "author", "uses"])
				if tag_name in [x[0] for x in tag_list]:
					tag_info = [x for x in tag_list if x[0] == tag_name][0]
					program = tag_info[1]
					uses = tag_info[3] + 1
					db.edit_entry("b++2programs", entry={"uses": uses, "lastused": time.time()}, conditions={"name": tag_name})
					author = tag_info[2]
				else:
					author = interaction.user.id

				if hash(program) not in LATEST_BUTTONS.keys() or LATEST_BUTTONS[hash(program)] <= interaction.message.id:
					await evaluate_and_send(
						program, custom_id.split(" ")[2:], author, interaction.user, interaction.message, True
					)

				await interaction.response.edit_message(view=None)
			except Exception as e:
				await interaction.response.send_message(
					embed=discord.Embed(
						color=0xFF0000,
						title=f"{type(e).__name__}",
						description=f"```{e}\n\n{traceback.format_tb(e.__traceback__)}```"
					),
					allowed_mentions=discord.AllowedMentions.none()
				)

		out_view = View()
		for button_value in buttons:
			if len(button_value) == 0:
				continue
			if len(button_value) == 1:
				button_value += ["​"]
			button = Button(
				label=button_value[1] if button_value[1] != "" else "​",
				style=discord.ButtonStyle.secondary,
				custom_id=f"{time.time()} {args[1]} {button_value[0]}",
				disabled=button_value[0] == "null"
			)
			button.callback = partial(button_callback, program)
			out_view.add_item(button)

		if len(program_output.strip()) == 0:
			program_output = "\u200b"

		if len(program_output) <= 2000:
			cmd_output = await source_message.reply(program_output, view=out_view, allowed_mentions=discord.AllowedMentions.none())
		elif len(program_output) <= 4096:
			cmd_output = await source_message.reply(
				embed=discord.Embed(description=program_output, type="rich"),
				view=out_view,
				allowed_mentions=discord.AllowedMentions.none()
			)
		else:
			open(f"Config/{source_message.id}out.txt", "w", encoding="utf-8").write(program_output[:150000])
			outfile = discord.File(f"Config/{source_message.id}out.txt")
			os.remove(f"Config/{source_message.id}out.txt")
			cmd_output = await source_message.reply(
				"⚠️ `Output too long! Sending first 150k characters in text file.`",
				file=outfile,
				view=out_view,
				allowed_mentions=discord.AllowedMentions.none()
			)

		if len(buttons) != 0:
			LATEST_BUTTONS[hash(program)] = cmd_output.id

		if len(unsaved_global_writes) != 0:
			shown = ", ".join([f"`{name}`" for name in unsaved_global_writes[:8]])
			extra = ""
			if len(unsaved_global_writes) > 8:
				extra = f" and {len(unsaved_global_writes) - 8} more"
			await source_message.channel.send(
				f"⚠️ GLOBAL variable changes are currently not persisted. Changed this run: {shown}{extra}.",
				allowed_mentions=discord.AllowedMentions.none()
			)

	await evaluate_and_send(program, program_args, author, runner, message)
