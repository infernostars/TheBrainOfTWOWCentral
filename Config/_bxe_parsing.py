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

	def persist(self):
		for variable in self._changed:
			value = self.global_variables[variable]
			value_type = _var_type(value)
			value_string = _encode_global_value(value)

			v_list = self._db.get_entries(
				"b++2variables", columns=["name", "value", "type", "owner"], conditions={"name": variable}
			)

			if len(v_list) == 0:
				self._db.add_entry("b++2variables", [variable, value_string, value_type, self._author])
				continue

			v_owner = str(v_list[0][3])
			if v_owner != self._author:
				raise PermissionError(
					f"Only the author of the {variable} variable can edit its value ({v_owner})"
				)

			self._db.edit_entry(
				"b++2variables",
				entry={"value": value_string, "type": value_type},
				conditions={"name": variable}
			)


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


def run_bxe_program(code, p_args, author, runner, channel):
	buttons = []
	try:
		tok = Tokenizer.tokenize(code)
		if isinstance(tok, TokenizationResult.Error):
			return [SyntaxError(f"{tok.message}\n\n{tok.range.debug_info()}"), buttons]

		par = Parser.parse(code, tok.tokens)
		if isinstance(par, ParsingResult.Error):
			return [SyntaxError(f"{par.message}\n\n{par.range.debug_info()}"), buttons]

		exe = Executor(
			extensions=[BuiltinExtension()],
			stateful_extensions=[
				_global_extension_factory(author),
				_discord_extension_factory(runner, channel),
			],
			program_args=p_args
		)

		result = exe.execute(par.nodes)
		if isinstance(result, ExecutorResult.Error):
			exc = result.exception
			span = getattr(exc, "span", None)
			if span is not None:
				try:
					exc = type(exc)(f"{exc}\n\n{span.debug_info()}")
				except Exception:
					pass
			return [exc, buttons]

		for ext in result.stateful_extensions:
			if isinstance(ext, BrainGlobalExtension):
				ext.persist()
			elif isinstance(ext, BrainDiscordExtension):
				buttons = ext.buttons

		return [result.output, buttons]
	except Exception as e:
		return [e, buttons]
