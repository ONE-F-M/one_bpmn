"""
Security validator for Logix-generated Frappe Server Scripts.

Two-pass scan:
1. AST walk  — catches all import statements, including aliased and from-imports.
2. Regex scan — catches exec/eval/open and dangerous raw SQL that AST cannot see at runtime.

Called by the ScriptTaskAgent pipeline before any code is shown to the user.
On failure the agent auto-regenerates with the violation list injected into the prompt.
"""

import ast
import re

# Python modules that must never appear in a Frappe Server Script
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

# (pattern, human-readable message [, re flags])
_PATTERNS: list[tuple] = [
	# File I/O
	(r"\bopen\s*\(",        "open() file access is not allowed"),
	# Code execution
	(r"\beval\s*\(",        "eval() is not allowed"),
	(r"\bexec\s*\(",        "exec() is not allowed"),
	(r"\b__import__\s*\(",  "__import__() is not allowed"),
	(r"\bcompile\s*\(",     "compile() is not allowed"),
	# Scope / reflection attacks
	(r"\bglobals\s*\(",     "globals() is not allowed"),
	(r"\blocals\s*\(",      "locals() is not allowed"),
	(r"\bvars\s*\(",        "vars() is not allowed"),
	(r"\b__builtins__\b",   "__builtins__ access is not allowed"),
	# Dunder MRO traversal
	(r"\.__mro__\b",        "MRO traversal is not allowed"),
	(r"\.__bases__\b",      "__bases__ access is not allowed"),
	# Dangerous raw SQL — destructive DDL/DML via frappe.db.sql
	(
		r"frappe\.db\.sql\s*\(.*?\b(DROP|TRUNCATE|ALTER|CREATE\s+TABLE)\b",
		"Destructive raw SQL (DROP/TRUNCATE/ALTER/CREATE TABLE) is not allowed",
		re.IGNORECASE | re.DOTALL,
	),
]


def validate_script(code: str) -> dict:
	"""
	Validate a generated server script for security violations.

	Returns:
		{"valid": True, "violations": []}
		{"valid": False, "violations": ["reason 1", ...]}
	"""
	violations: list[str] = []

	# ── Pass 1: AST import scan ────────────────────────────────────────
	try:
		tree = ast.parse(code)
	except SyntaxError as exc:
		return {"valid": False, "violations": [f"Syntax error in generated code: {exc}"]}

	for node in ast.walk(tree):
		if isinstance(node, ast.Import):
			for alias in node.names:
				top = alias.name.split(".")[0]
				if top in FORBIDDEN_MODULES:
					violations.append(f"Forbidden import: '{alias.name}'")

		elif isinstance(node, ast.ImportFrom):
			top = (node.module or "").split(".")[0]
			if top in FORBIDDEN_MODULES:
				violations.append(f"Forbidden import: 'from {node.module} import ...'")

	# ── Pass 2: regex pattern scan ─────────────────────────────────────
	for entry in _PATTERNS:
		pattern, message = entry[0], entry[1]
		flags = entry[2] if len(entry) > 2 else 0
		if re.search(pattern, code, flags):
			violations.append(message)

	return {"valid": len(violations) == 0, "violations": violations}
