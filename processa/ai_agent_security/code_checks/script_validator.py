"""
Security check for BPMN Script Tasks and Server Scripts.

Walks the AST once and reports each module, Frappe function, builtin and shape whose
Script Import Category needs approval, with its line. An import of a module in no
category is Unlisted. Every entry point (Server Script save, map deploy, the run-time
check before exec and the AI pipeline) goes through inspect_script.
"""

import ast
import builtins
import re

from processa.ai_agent_security.code_checks.script_categories import (
	UNLISTED,
	attribute_category,
	category_for,
	category_threshold,
	needs_approval,
)

MODULE = "Module"
FUNCTION = "Frappe function"
BUILTIN = "Builtin"
SYNTAX = "Syntax"
SYNTAX_ERROR = "Syntax error"
IMPORT_ERROR = "Script import"
# Findings that no approval can cover.
NOT_APPROVABLE = frozenset({SYNTAX_ERROR, IMPORT_ERROR})

# Attributes that climb from any object to the interpreter globals.
_OBJECT_GRAPH_ATTRIBUTES = frozenset({
	"gi_frame", "f_back", "f_globals", "f_locals", "f_code",
	"__dict__", "__code__", "__globals__", "__subclasses__",
	"__class__", "__base__", "__bases__", "__mro__",
	"__builtins__", "__closure__", "__func__", "__self__",
})
# Builtins with no legitimate attribute form, caught when reached as obj.exec().
_CALL_ATTRIBUTE_BUILTINS = frozenset({"exec", "eval", "__import__"})
_PERMISSION_KWARGS = frozenset({"ignore_permissions"})
_PROTECTED_STATE_ATTRIBUTES = frozenset({"flags", "session"})
_MUTATING_METHODS = frozenset({"update", "setdefault", "pop", "popitem", "clear", "__setitem__"})
_DESTRUCTIVE_SQL_RE = re.compile(
	r"frappe\.db\.sql\s*\(.*?\b(DROP|TRUNCATE|ALTER|CREATE\s+TABLE)\b",
	re.IGNORECASE | re.DOTALL,
)
# Used when the category holding large_multiplication has no Threshold.
_DEFAULT_MULTIPLY_THRESHOLD = 50000
_LANGUAGE_CONSTRUCTS = {
	"while": "`while` loops",
	"def": "`def` functions",
	"lambda": "`lambda`",
	"class": "`class` definitions",
}


def site_gate_rules() -> str:
	"""Whether this site's gate accepts each language construct, one line each."""
	return "\n".join(
		f"- {label}: {'needs approval' if needs_approval(category_for(name)) else 'accepted'} on this site."
		for name, label in _LANGUAGE_CONSTRUCTS.items()
	)


def parse_allowed(text: str | None) -> frozenset:
	"""The entries of an allowed modules field, one per line or comma-separated."""
	return frozenset(filter(None, re.split(r"[\s,]+", text or "")))


class _SecurityVisitor(ast.NodeVisitor):
	"""Walk the AST once, collecting findings."""

	def __init__(self, allowed: frozenset):
		self.allowed = allowed
		self.frappe_aliases = {"frappe": "frappe"}
		self.findings: list[dict] = []
		self._node: ast.AST | None = None

	def visit(self, node: ast.AST) -> None:
		parent, self._node = self._node, node
		super().visit(node)
		self._node = parent

	def report(self, name, kind, category=None, unlisted=False, detail="", line=None) -> None:
		"""Record name when its category needs approval and the script's approval does not cover it."""
		category = category or category_for(name)
		if category == UNLISTED and not unlisted:
			return
		parts = name.split(".")
		if not needs_approval(category) or any(".".join(parts[:end]) in self.allowed for end in range(1, len(parts) + 1)):
			return
		self.findings.append({
			"category": category,
			"name": name,
			"kind": kind,
			"line": line or getattr(self._node, "lineno", None),
			"message": f"{detail or name} needs approval ({category})",
		})

	# ── imports ──────────────────────────────────────────────────────────
	def visit_Import(self, node: ast.Import) -> None:
		for alias in node.names:
			if alias.name.split(".")[0] == "frappe":
				self.frappe_aliases[alias.asname or "frappe"] = alias.name if alias.asname else "frappe"
				self.report(alias.name, FUNCTION)
			else:
				self.report(alias.name, MODULE, unlisted=True)
		self.generic_visit(node)

	def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
		module = node.module or ""
		from_frappe = module.split(".")[0] == "frappe"
		for alias in node.names:
			if alias.name == "*":
				self.report(
					f"from {module} import *", SYNTAX, category="Dynamic code and reflection", unlisted=True
				)
				continue
			name = f"{module}.{alias.name}"
			if from_frappe:
				self.frappe_aliases[alias.asname or alias.name] = name
				self.report(name, FUNCTION)
			else:
				self.report(name, MODULE, unlisted=True)
		self.generic_visit(node)

	def visit_Assign(self, node: ast.Assign) -> None:
		if len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
			dotted = self._dotted(node.value)
			if dotted:
				self.frappe_aliases[node.targets[0].id] = dotted
		self.generic_visit(node)

	def _dotted(self, node: ast.expr) -> str | None:
		"""``frappe.db.sql`` for an attribute chain rooted at frappe or an alias of it, else None."""
		if isinstance(node, ast.Name):
			return self.frappe_aliases.get(node.id)
		if isinstance(node, ast.Attribute):
			base = self._dotted(node.value)
			return f"{base}.{node.attr}" if base else None
		return None

	# ── calls: builtins, attribute exec, state mutation, permission kwargs ─
	def visit_Call(self, node: ast.Call) -> None:
		func = node.func
		if isinstance(func, ast.Name):
			self.report(func.id, BUILTIN, detail=f"{func.id}()")
			if func.id == "import_script" and not _script_name_argument(node):
				self.findings.append(
					import_error("import_script", node.lineno, "import_script needs the script name in quotes")
				)
		elif isinstance(func, ast.Attribute) and func.attr in _CALL_ATTRIBUTE_BUILTINS:
			self.report(func.attr, BUILTIN, detail=f".{func.attr}()")
		if (
			isinstance(func, ast.Attribute)
			and func.attr in _MUTATING_METHODS
			and _node_name(func.value) in _PROTECTED_STATE_ATTRIBUTES
		):
			self.report("session_write", SYNTAX, unlisted=True, detail=f".{_node_name(func.value)}.{func.attr}()")
		for kw in node.keywords:
			if kw.arg is None:
				self._check_kwargs_unpack(kw.value)
			elif kw.arg in _PERMISSION_KWARGS:
				self.report("permission_kwarg", SYNTAX, unlisted=True, detail=f"{kw.arg}=...")
		self.generic_visit(node)

	def _check_kwargs_unpack(self, value: ast.expr) -> None:
		if not isinstance(value, ast.Dict):
			return
		for key in value.keys:
			if isinstance(key, ast.Constant) and key.value in _PERMISSION_KWARGS:
				self.report("permission_kwarg", SYNTAX, unlisted=True, detail=f"**{{'{key.value}': ...}}")
			elif key is not None and not isinstance(key, ast.Constant):
				self.report("permission_kwarg", SYNTAX, unlisted=True, detail="A computed keyword in **kwargs")

	# ── attribute access ─────────────────────────────────────────────────
	def visit_Attribute(self, node: ast.Attribute) -> None:
		attr = node.attr
		if attr in _OBJECT_GRAPH_ATTRIBUTES:
			self.report("dunder_attribute", SYNTAX, unlisted=True, detail=f".{attr}")
		self._check_session_write(node)
		dotted = self._dotted(node)
		if dotted and category_for(dotted) != UNLISTED:
			# The rest of the chain is frappe and its attributes, already covered by the full name.
			self.report(dotted, FUNCTION)
			return
		category = attribute_category(attr)
		if category:
			self.report(attr, FUNCTION, category=category)
		self.generic_visit(node)

	def visit_Name(self, node: ast.Name) -> None:
		if node.id == "__builtins__":
			self.report("dunder_attribute", SYNTAX, unlisted=True, detail="__builtins__")

	def _check_session_write(self, node: ast.Attribute | ast.Subscript) -> None:
		if isinstance(node.ctx, (ast.Store, ast.Del)) and _node_name(node.value) == "session":
			self.report("session_write", SYNTAX, unlisted=True, detail="Writing to the request session")

	# ── subscript string lookup:  frappe["__dict__"], obj["f_back"] ──────
	def visit_Subscript(self, node: ast.Subscript) -> None:
		key = node.slice.value if isinstance(node.slice, ast.Constant) else None
		if isinstance(key, str):
			if key in _OBJECT_GRAPH_ATTRIBUTES or _is_dunder(key):
				self.report("dunder_subscript", SYNTAX, unlisted=True, detail=f"['{key}']")
			elif category := attribute_category(key):
				self.report(key, FUNCTION, category=category, detail=f"['{key}']")
		self._check_session_write(node)
		self.generic_visit(node)

	# ── language constructs ──────────────────────────────────────────────
	def visit_While(self, node: ast.While) -> None:
		self.report("while", SYNTAX)
		self.generic_visit(node)

	def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
		self.report("def", SYNTAX, detail=f"def {node.name}")
		self.generic_visit(node)

	def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
		self.report("def", SYNTAX, detail=f"async def {node.name}")
		self.generic_visit(node)

	def visit_Lambda(self, node: ast.Lambda) -> None:
		self.report("lambda", SYNTAX)
		self.generic_visit(node)

	def visit_ClassDef(self, node: ast.ClassDef) -> None:
		self.report("class", SYNTAX, detail=f"class {node.name}")
		self.generic_visit(node)

	# ── memory-bomb multiplication:  "A" * 999999999 ────────────────────
	def visit_BinOp(self, node: ast.BinOp) -> None:
		if isinstance(node.op, ast.Mult):
			category = category_for("large_multiplication")
			threshold = category_threshold(category) or _DEFAULT_MULTIPLY_THRESHOLD
			for operand in (node.left, node.right):
				if (
					isinstance(operand, ast.Constant)
					and isinstance(operand.value, int)
					and not isinstance(operand.value, bool)
					and operand.value > threshold
				):
					self.report(
						"large_multiplication",
						SYNTAX,
						category=category,
						unlisted=True,
						detail=f"Multiplying by {operand.value}, above the threshold of {threshold},",
					)
					break
		self.generic_visit(node)


def import_error(name: str, line: int | None, message: str) -> dict:
	"""A finding about import_script, which no approval can cover."""
	return {"category": IMPORT_ERROR, "name": name, "kind": SYNTAX, "line": line, "message": message}


def imported_scripts(code: str | None) -> list[tuple[str, int]]:
	"""Each script name code passes to import_script in quotes, with its line."""
	try:
		tree = ast.parse(code or "")
	except SyntaxError:
		return []
	return [
		(_script_name_argument(node), node.lineno)
		for node in ast.walk(tree)
		if isinstance(node, ast.Call)
		and isinstance(node.func, ast.Name)
		and node.func.id == "import_script"
		and _script_name_argument(node)
	]


def _script_name_argument(node: ast.Call) -> str | None:
	if len(node.args) == 1 and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
		return node.args[0].value
	return None


def _is_dunder(name: str) -> bool:
	return len(name) > 4 and name.startswith("__") and name.endswith("__")


def _node_name(node: ast.expr) -> str | None:
	if isinstance(node, ast.Attribute):
		return node.attr
	if isinstance(node, ast.Name):
		return node.id
	return None


def inspect_script(code: str | None, allowed: frozenset = frozenset()) -> list[dict]:
	"""Each finding in code as {category, name, kind, line, message}; empty when clean.

	allowed holds the names an approved script may use. A script that does not parse gives one Syntax error finding.
	"""
	code = code or ""
	try:
		tree = ast.parse(code)
	except SyntaxError as exc:
		return [{
			"category": SYNTAX_ERROR,
			"name": "",
			"kind": SYNTAX,
			"line": exc.lineno,
			"message": f"Syntax error on line {exc.lineno}: {exc.msg}",
		}]
	visitor = _SecurityVisitor(allowed)
	visitor.visit(tree)
	if match := _DESTRUCTIVE_SQL_RE.search(code):
		visitor.report(
			"destructive_sql",
			SYNTAX,
			unlisted=True,
			detail="Destructive SQL (DROP/TRUNCATE/ALTER/CREATE TABLE)",
			line=code.count("\n", 0, match.start()) + 1,
		)
	return visitor.findings


def deep_inspect_script(script_text: str | None, allowed: frozenset = frozenset()) -> list[str]:
	"""The message of each finding in script_text; empty when clean."""
	return [finding["message"] for finding in inspect_script(script_text, allowed)]


def validate_script(code: str) -> dict:
	"""{"valid", "violations", "findings"} for the AI pipeline; each finding is {rule, line, code, category, name}."""
	code = code or ""
	source_lines = code.splitlines()
	found = inspect_script(code)
	return {
		"valid": not found,
		"violations": [f["message"] for f in found],
		"findings": [
			{
				"rule": f["message"],
				"line": f["line"],
				"code": source_lines[f["line"] - 1].strip() if f["line"] and f["line"] <= len(source_lines) else "",
				"category": f["category"],
				"name": f["name"],
			}
			for f in found
		],
	}


# Names a BPMN Script Task receives without defining them; anything else must be defined or imported.
INJECTED_NAMES = ("frappe", "doc", "task_data", "result", "context_doctype", "context_docname", "import_script")
_BUILTIN_NAMES = frozenset(dir(builtins))
_CLIENT_SCRIPT_RE = re.compile(r"\b(client[\s-]?script|form script|javascript|js)\b", re.IGNORECASE)
_SERVER_SCRIPT_RE = re.compile(r"\b(server[\s-]?script|python)\b", re.IGNORECASE)
_REQUEST_NUMBER_RE = re.compile(r"(?<![\w.\-/:])\d+(?:\.\d+)?(?![\w.\-/:])")
_REPLACED_NUMBER_RE = re.compile(r"\b(?:not|instead of|rather than|from)\s+(\d+(?:\.\d+)?)", re.IGNORECASE)
_CODE_NUMBER_RE = re.compile(r"(?<![\w.])\d+(?:\.\d+)?(?![\w.])")
# Words that make a number in the request a value the script must use, not a count of things to change.
_LIMIT_WORDS = frozenset(
	"limit limits max maximum min minimum least most top latest last first oldest newest only exactly "
	"days day hours hour minutes minute seconds weeks week months month years year records record rows row "
	"items item results result entries times retries retry attempts percent threshold than over under above "
	"below after before within every per not from instead rather".split()
)


def request_findings(code: str, request: str, language: str = "python") -> list[dict]:
	"""Findings for a generated script that would not run or does not follow the request, as {"rule", "line", "code"}."""
	findings = _script_type_findings(request, language)
	if language == "python":
		findings += undefined_name_findings(code)
	return findings + _number_findings(code, request)


def _script_type_findings(request: str, language: str) -> list[dict]:
	from frappe import _

	wants_client = bool(_CLIENT_SCRIPT_RE.search(request))
	wants_server = bool(_SERVER_SCRIPT_RE.search(request))
	if wants_client == wants_server:
		return []
	if wants_client and language == "python":
		rule = _(
			"The request asks for a client script (JavaScript that runs on the form), but this is a "
			"server script in Python. Return the client script in a ```javascript block."
		)
		return [{"rule": rule, "line": 0, "code": ""}]
	if wants_server and language == "javascript":
		rule = _(
			"The request asks for a server script, but this is JavaScript. Return the server script in a ```python block."
		)
		return [{"rule": rule, "line": 0, "code": ""}]
	return []


def undefined_name_findings(code: str) -> list[dict]:
	"""One finding per name the script reads but never injects, defines or imports, at its first use."""
	from frappe import _

	try:
		tree = ast.parse(code)
	except SyntaxError:
		return []
	bound = set(INJECTED_NAMES) | _BUILTIN_NAMES
	used = []
	for node in ast.walk(tree):
		if isinstance(node, ast.Name):
			if isinstance(node.ctx, ast.Load):
				used.append(node)
			else:
				bound.add(node.id)
		elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
			bound.add(node.name)
		elif isinstance(node, ast.arg):
			bound.add(node.arg)
		elif isinstance(node, ast.alias):
			bound.add((node.asname or node.name).split(".")[0])
		elif isinstance(node, (ast.Global, ast.Nonlocal)):
			bound.update(node.names)
		elif isinstance(node, (ast.ExceptHandler, ast.MatchAs, ast.MatchStar)) and node.name:
			bound.add(node.name)
		elif isinstance(node, ast.MatchMapping) and node.rest:
			bound.add(node.rest)

	lines = code.splitlines()
	findings = []
	reported = set()
	for node in sorted(used, key=lambda n: (n.lineno, n.col_offset)):
		if node.id in bound or node.id in reported:
			continue
		reported.add(node.id)
		findings.append(
			{
				"rule": _(
					"`{0}` is used but never defined or imported, and a Script Task only receives {1}"
				).format(node.id, ", ".join(INJECTED_NAMES)),
				"line": node.lineno,
				"code": lines[node.lineno - 1].strip(),
			}
		)
	return findings


def _number_findings(code: str, request: str) -> list[dict]:
	"""A number the request asks for that the script replaced with a number of its own."""
	from frappe import _

	replaced = set(_REPLACED_NUMBER_RE.findall(request))
	words = re.findall(r"[a-z]+|\d+(?:\.\d+)?|%", request.lower())
	wanted = []
	for i, word in enumerate(words):
		if not _REQUEST_NUMBER_RE.fullmatch(word) or word in replaced:
			continue
		near = set(words[max(0, i - 3) : i + 4])
		if near & _LIMIT_WORDS or "%" in near:
			wanted.append(word)
	wanted = list(dict.fromkeys(wanted))
	in_code = set(_CODE_NUMBER_RE.findall(code))
	own = sorted(in_code - set(wanted) - {"0", "1"}, key=float)
	if not own:
		return []
	return [
		{
			"rule": _(
				"The request says {0}, but the script uses {1} instead. Use the request's numbers exactly."
			).format(n, ", ".join(own)),
			"line": 0,
			"code": "",
		}
		for n in wanted
		if n not in in_code
	]
