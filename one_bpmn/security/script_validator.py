"""
Security validator for BPMN Script Tasks (Frappe Server Scripts).

This module is the single source of truth for script security in one_bpmn.
Every entry point — the AI-generation pipeline, Server Script save, process-model
authoring, and process-model deploy — funnels through ``deep_inspect_script``.

Design: a structural Abstract Syntax Tree (AST) analyser, NOT a keyword
blacklist. A blacklist is trivially bypassed via string formatting, dynamic
attribute lookup, or sandbox-escape gadgets; walking the AST catches the
*shape* of an attack regardless of how it is spelled.

Enforcement model: PRE-DEPLOYMENT GATE. Validation runs when a script is
authored/saved and again when a model is deployed — never at execution time.
The intent is to prevent an unsafe script from ever being added or deployed.

Tuning (per the agreed decisions):
  * Unambiguous escape vectors are ALWAYS blocked (exec/eval/getattr,
    frame-walking dunders, __globals__, subscript dunder lookups, imports of
    dangerous modules, memory-bomb multiplication, permission-bypass kwargs).
  * Constructs that also have legitimate uses are CONFIG-GATED and default to
    ALLOW, so the gate does not reject ordinary Frappe scripts wholesale:
        - control flow: while / def / lambda   (block_while / block_functiondef / block_lambda)
        - soft builtins: hasattr / type / id / classmethod / staticmethod  (strict_builtins)
        - soft frappe attrs: sql / commit / flags / conf / cache           (strict_frappe_attrs)
        - all imports:                                                       (block_all_imports)
  * Overrides live on the **Processa Settings** single doctype (see
    ``_resolve_options``) so an operator can tighten the posture from the desk
    UI without a code change.

Public API:
  deep_inspect_script(script_text, options=None) -> list[str]
      Structural analysis. Returns a list of human-readable violation
      messages (empty when clean), or a single-element list with a syntax-error
      message when the script does not parse.

  validate_script(code) -> dict
      Back-compatible wrapper used by the AI pipeline.
      Returns {"valid": bool, "violations": [...]}.
"""

import ast
import re

# ── Python modules that must never appear in a Frappe Server Script ──────────
FORBIDDEN_MODULES = frozenset({
	# OS / shell / process
	"os", "sys", "subprocess", "signal", "pty", "atexit",
	# Networking
	"socket", "ssl", "requests", "urllib", "urllib2", "urllib3",
	"http", "ftplib", "smtplib", "telnetlib", "imaplib", "poplib",
	# Serialisation / code execution
	"pickle", "marshal", "shelve", "dill", "cloudpickle",
	# Low-level / FFI
	"ctypes", "cffi", "mmap",
	# Concurrency (no background threads in scripts)
	"multiprocessing", "threading", "concurrent",
	# Dynamic code loading
	"importlib", "pkgutil", "types",
	# Reflection / introspection
	"inspect", "dis", "gc", "traceback",
	# File-system helpers
	"tempfile", "shutil", "pathlib", "glob",
})

# ── Builtins that are pure escape/reflection vectors — ALWAYS blocked ─────────
# getattr/setattr/delattr are the classic dynamic-attribute bypass:
#   getattr(frappe, "__" + "globals__")  defeats any attribute blacklist.
BANNED_BUILTINS = frozenset({
	"exec", "eval", "compile", "__import__", "open",
	"globals", "locals", "vars", "dir",
	"getattr", "setattr", "delattr",
})

# Builtins with common legitimate uses — blocked only when strict_builtins is on.
SOFT_BANNED_BUILTINS = frozenset({
	"hasattr", "type", "id", "classmethod", "staticmethod",
})

# ── Attributes that are pure escape vectors — ALWAYS blocked ──────────────────
# Frame-walking + object-graph traversal dunders let a script climb from any
# object to the interpreter globals and rebuild banned builtins.
BANNED_ATTRIBUTES = frozenset({
	# frame / generator / code walking
	"gi_frame", "f_back", "f_globals", "f_locals", "f_code",
	# object-graph traversal
	"__dict__", "__code__", "__globals__", "__subclasses__",
	"__class__", "__base__", "__bases__", "__mro__",
	"__builtins__", "__closure__", "__func__", "__self__",
})

# Frappe internals that bypass the permission / durability model — ALWAYS blocked.
BANNED_FRAPPE_ATTRIBUTES = frozenset({
	"ignore_permissions", "db_update", "add_roles",
})

# Frappe internals that are sensitive but often legitimate (frappe.db.sql for
# reads, frappe.conf for config, frappe.cache() ...) — blocked only when
# strict_frappe_attrs is on. Destructive raw SQL is caught separately, always.
SOFT_BANNED_FRAPPE_ATTRIBUTES = frozenset({
	"sql", "commit", "flags", "conf", "cache",
})

# Keyword arguments that inject a permission bypass into a save/insert/submit call.
PERMISSION_BYPASS_KWARGS = frozenset({
	"ignore_permissions",
})

# Destructive raw SQL — DDL/DML that a Server Script must never issue.
_DESTRUCTIVE_SQL_RE = re.compile(
	r"frappe\.db\.sql\s*\(.*?\b(DROP|TRUNCATE|ALTER|CREATE\s+TABLE)\b",
	re.IGNORECASE | re.DOTALL,
)

# Processa Settings field → ValidatorOptions attribute, with defaults.
_SETTINGS_FIELDS = {
	"script_block_while": ("block_while", False),
	"script_block_functiondef": ("block_functiondef", False),
	"script_block_lambda": ("block_lambda", False),
	"script_strict_builtins": ("strict_builtins", False),
	"script_strict_frappe_attrs": ("strict_frappe_attrs", False),
	"script_block_all_imports": ("block_all_imports", False),
	"script_binop_multiply_threshold": ("binop_multiply_threshold", 50000),
}


class ValidatorOptions:
	"""Tunable posture for :func:`deep_inspect_script`."""

	__slots__ = (
		"block_while",
		"block_functiondef",
		"block_lambda",
		"strict_builtins",
		"strict_frappe_attrs",
		"block_all_imports",
		"binop_multiply_threshold",
	)

	def __init__(
		self,
		block_while: bool = False,
		block_functiondef: bool = False,
		block_lambda: bool = False,
		strict_builtins: bool = False,
		strict_frappe_attrs: bool = False,
		block_all_imports: bool = False,
		binop_multiply_threshold: int = 50000,
	):
		self.block_while = block_while
		self.block_functiondef = block_functiondef
		self.block_lambda = block_lambda
		self.strict_builtins = strict_builtins
		self.strict_frappe_attrs = strict_frappe_attrs
		self.block_all_imports = block_all_imports
		self.binop_multiply_threshold = binop_multiply_threshold


def _resolve_options() -> ValidatorOptions:
	"""
	Build :class:`ValidatorOptions` from the Processa Settings single doctype.

	Defensive: if ``frappe`` is not importable (unit tests, tooling) or the
	doctype is not yet installed, the secure-but-usable defaults apply.
	"""
	opts = ValidatorOptions()
	try:
		import frappe as _f

		settings = _f.get_cached_doc("Processa Settings")
	except Exception:
		return opts

	for field, (attr, default) in _SETTINGS_FIELDS.items():
		value = getattr(settings, field, None)
		if value is None:
			continue
		if isinstance(default, bool):
			setattr(opts, attr, bool(value))
		else:
			# Threshold: ignore unset/zero/malformed values, keep the default.
			try:
				parsed = int(value)
			except (TypeError, ValueError):
				continue
			if parsed > 0:
				setattr(opts, attr, parsed)
	return opts


class _SecurityVisitor(ast.NodeVisitor):
	"""Walk the AST once, collecting security violations."""

	def __init__(self, options: ValidatorOptions):
		self.options = options
		self.violations: list[str] = []

	# ── imports ──────────────────────────────────────────────────────────
	def visit_Import(self, node: ast.Import) -> None:
		for alias in node.names:
			top = alias.name.split(".")[0]
			if self.options.block_all_imports:
				self.violations.append(f"Import statements are not allowed: 'import {alias.name}'")
			elif top in FORBIDDEN_MODULES:
				self.violations.append(f"Forbidden import: '{alias.name}'")
		self.generic_visit(node)

	def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
		module = node.module or ""
		top = module.split(".")[0]
		if self.options.block_all_imports:
			self.violations.append(f"Import statements are not allowed: 'from {module} import ...'")
		elif top in FORBIDDEN_MODULES:
			self.violations.append(f"Forbidden import: 'from {module} import ...'")
		self.generic_visit(node)

	# ── calls: banned builtins + kwargs permission injection ─────────────
	def visit_Call(self, node: ast.Call) -> None:
		func = node.func
		if isinstance(func, ast.Name):
			name = func.id
			if name in BANNED_BUILTINS:
				self.violations.append(f"{name}() is not allowed")
			elif name in SOFT_BANNED_BUILTINS and self.options.strict_builtins:
				self.violations.append(f"{name}() is not allowed (strict mode)")

		# explicit  save(ignore_permissions=True)
		for kw in node.keywords:
			if kw.arg is None:
				# dict-unpack:  save(**{"ignore_permissions": True})
				self._check_kwargs_unpack(kw.value)
			elif kw.arg in PERMISSION_BYPASS_KWARGS:
				self.violations.append(
					f"Permission-bypass keyword '{kw.arg}=...' is not allowed"
				)
		self.generic_visit(node)

	def _check_kwargs_unpack(self, value: ast.expr) -> None:
		if not isinstance(value, ast.Dict):
			return
		for key in value.keys:
			if isinstance(key, ast.Constant) and key.value in PERMISSION_BYPASS_KWARGS:
				self.violations.append(
					f"Permission-bypass keyword '{key.value}' injected via **kwargs is not allowed"
				)

	# ── attribute access ─────────────────────────────────────────────────
	def visit_Attribute(self, node: ast.Attribute) -> None:
		attr = node.attr
		if attr in BANNED_ATTRIBUTES:
			self.violations.append(f"Access to '.{attr}' is not allowed")
		elif attr in BANNED_FRAPPE_ATTRIBUTES:
			self.violations.append(f"Access to Frappe internal '.{attr}' is not allowed")
		elif attr in SOFT_BANNED_FRAPPE_ATTRIBUTES and self.options.strict_frappe_attrs:
			self.violations.append(f"Access to '.{attr}' is not allowed (strict mode)")
		self.generic_visit(node)

	# ── subscript string lookup:  frappe["__dict__"], obj["f_back"] ──────
	def visit_Subscript(self, node: ast.Subscript) -> None:
		key = self._subscript_key(node)
		if isinstance(key, str):
			if key in BANNED_ATTRIBUTES or key in BANNED_FRAPPE_ATTRIBUTES or _is_dunder(key):
				self.violations.append(
					f"Subscript lookup of '{key}' is not allowed (attribute-access bypass)"
				)
			elif key in SOFT_BANNED_FRAPPE_ATTRIBUTES and self.options.strict_frappe_attrs:
				self.violations.append(f"Subscript lookup of '{key}' is not allowed (strict mode)")
		self.generic_visit(node)

	@staticmethod
	def _subscript_key(node: ast.Subscript):
		sl = node.slice
		# py3.9+: the constant is the slice directly; older wrapped in ast.Index
		if isinstance(sl, ast.Constant):
			return sl.value
		if isinstance(sl, ast.Index) and isinstance(sl.value, ast.Constant):  # pragma: no cover
			return sl.value.value
		return None

	# ── control flow (config-gated, default allow) ───────────────────────
	def visit_While(self, node: ast.While) -> None:
		if self.options.block_while:
			self.violations.append(
				"while loops are not allowed — use a BPMN gateway/loop for iteration"
			)
		self.generic_visit(node)

	def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
		if self.options.block_functiondef:
			self.violations.append(
				f"Function definitions are not allowed ('def {node.name}')"
			)
		self.generic_visit(node)

	def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
		if self.options.block_functiondef:
			self.violations.append(
				f"Function definitions are not allowed ('async def {node.name}')"
			)
		self.generic_visit(node)

	def visit_Lambda(self, node: ast.Lambda) -> None:
		if self.options.block_lambda:
			self.violations.append("lambda expressions are not allowed")
		self.generic_visit(node)

	# ── memory-bomb multiplication:  "A" * 999999999 ────────────────────
	def visit_BinOp(self, node: ast.BinOp) -> None:
		if isinstance(node.op, ast.Mult):
			threshold = self.options.binop_multiply_threshold
			for operand in (node.left, node.right):
				if (
					isinstance(operand, ast.Constant)
					and isinstance(operand.value, int)
					and not isinstance(operand.value, bool)
					and operand.value > threshold
				):
					self.violations.append(
						f"Multiplication factor {operand.value} exceeds the "
						f"memory-safety threshold of {threshold}"
					)
					break
		self.generic_visit(node)


def _is_dunder(name: str) -> bool:
	return len(name) > 4 and name.startswith("__") and name.endswith("__")


def deep_inspect_script(script_text: str, options: "ValidatorOptions | None" = None) -> list[str]:
	"""
	Structurally inspect a script for security violations.

	Args:
		script_text: the Python source of a Server Script / inline script task.
		options:     tunable posture; when omitted, resolved from site_config.

	Returns:
		A list of human-readable violation messages (empty when the script is
		clean), or a single-element list containing a syntax-error message when
		the script does not parse.
	"""
	if options is None:
		options = _resolve_options()

	code = script_text or ""

	try:
		tree = ast.parse(code)
	except SyntaxError as exc:
		return [f"Syntax error in script: {exc}"]

	visitor = _SecurityVisitor(options)
	visitor.visit(tree)
	violations = list(visitor.violations)

	# Destructive raw SQL is a string-content concern, not a structural one.
	if _DESTRUCTIVE_SQL_RE.search(code):
		violations.append(
			"Destructive raw SQL (DROP/TRUNCATE/ALTER/CREATE TABLE) is not allowed"
		)

	# __builtins__ can appear as a bare name too (not only as an attribute).
	if re.search(r"\b__builtins__\b", code) and not any("__builtins__" in v for v in violations):
		violations.append("__builtins__ access is not allowed")

	return violations


def validate_script(code: str) -> dict:
	"""
	Back-compatible wrapper for the AI-generation pipeline.

	Returns:
		{"valid": True, "violations": []}
		{"valid": False, "violations": ["reason 1", ...]}
	"""
	violations = deep_inspect_script(code)
	return {"valid": len(violations) == 0, "violations": violations}
