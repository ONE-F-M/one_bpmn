# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""
Filesystem primitives for agent tools that read the bench's own code.

WHY THIS IS A MODULE AND NOT A SERVER SCRIPT (WI-001634)
--------------------------------------------------------
Agent tools are Server Scripts on an ad-hoc "Tools" sub-process, and every BPMN
Script Task passes ``one_bpmn.security.script_validator.deep_inspect_script``
before it can be saved or deployed. That gate permanently forbids ``os``,
``glob``, ``pathlib`` and the ``open()`` builtin — a script cannot walk or read
the filesystem, by design. So the primitives live here, and the tool script owns
everything else.

The split is deliberate and minimal: this module returns RAW structure (which
DocTypes exist and where their files are, what each app's hooks.py declares,
which functions carry @frappe.whitelist()). It holds no matching, scoring,
ranking, thresholds or narrative — all of that is LuCrusher's analysis and lives
in the "LuCrusher – Tool Scan Codebase" Server Script. Same shape as the Docu
migration keeping its deterministic ``tools.py`` helpers while the pipeline logic
moved into the map.

Nothing here is agent-specific, so any future agent that needs to read the bench
can call it.

Caching: the DocType + hooks index is cached in Redis for an hour (hooks.py and
the DocType list barely move). The @frappe.whitelist() walk is per-call but
bounded by its ``apps`` and ``path_keywords`` arguments.
"""

from __future__ import annotations

import ast
import glob
import os
import re

import frappe

INDEX_CACHE_KEY = "lucrusher_codebase_index_v2"
INDEX_TTL = 3600  # 1 hour

# hooks.py top-level assignments worth reporting.
HOOK_KEYS = frozenset({
	"doc_events",
	"override_doctype_class",
	"scheduler_events",
	"override_whitelisted_methods",
	"permission_query_conditions",
	"has_permission",
})

_FALLBACK_APPS = ("frappe", "erpnext", "one_fm", "hrms", "one_bpmn", "onefm_mcp")

_WHITELIST_DECORATOR = "@frappe.whitelist"
_DEF_RE = re.compile(r"(?:async\s+)?def\s+(\w+)\s*\(")


def get_apps_root() -> str:
	"""Absolute path to the bench's ``apps/`` directory."""
	# frappe.get_app_path('frappe') -> .../bench/apps/frappe/frappe
	return os.path.dirname(os.path.dirname(frappe.get_app_path("frappe")))


def _installed_apps() -> list:
	try:
		return frappe.get_installed_apps()
	except Exception:
		return list(_FALLBACK_APPS)


def _module_app_map(apps_root: str, installed_apps: list) -> dict:
	"""``{module_name: app_name}``.

	Prefers Frappe's runtime mapping (populated at request startup); falls back
	to reading each app's modules.txt, which is what background workers need.
	"""
	runtime_map = getattr(frappe.local, "module_app", None) or {}
	if runtime_map:
		return dict(runtime_map)

	mapping = {}
	for app in installed_apps:
		modules_txt = os.path.join(apps_root, app, app, "modules.txt")
		if not os.path.isfile(modules_txt):
			continue
		try:
			with open(modules_txt, encoding="utf-8", errors="ignore") as fh:
				for raw_line in fh:
					module = raw_line.strip()
					if module:
						mapping[module] = app
		except Exception:
			pass
	return mapping


def _doctypes(module_app: dict, apps_root: str) -> list:
	"""Every DocType with its app, module and conventional file paths.

	``py_exists`` is resolved here so callers never need an isfile() of their
	own (they cannot make one).
	"""
	entries = []
	try:
		doctypes = frappe.get_all("DocType", fields=["name", "module"])
	except Exception:
		frappe.log_error(title="Codebase index — DocType scan", message=frappe.get_traceback())
		return entries

	for dt in doctypes:
		name = (dt.get("name") or "").strip()
		module = (dt.get("module") or "").strip()
		if not name:
			continue
		app = module_app.get(frappe.scrub(module)) or module_app.get(module, "")
		snake_name = name.lower().replace(" ", "_")
		module_snake = module.lower().replace(" ", "_")
		json_file = py_file = ""
		if app:
			base = f"{app}/{app}/{module_snake}/doctype/{snake_name}/{snake_name}"
			json_file = f"{base}.json"
			py_file = f"{base}.py"
		entries.append({
			"name": name,
			"app": app,
			"module": module,
			"file": json_file,
			"py_file": py_file,
			"py_exists": bool(py_file) and os.path.isfile(os.path.join(apps_root, py_file)),
		})
	return entries


def _parse_hooks_py(hooks_path: str) -> dict:
	"""Read the hook keys out of a hooks.py with ``ast.literal_eval``.

	The file is never imported or executed.
	"""
	out = {}
	try:
		with open(hooks_path, encoding="utf-8", errors="ignore") as fh:
			source = fh.read()
		tree = ast.parse(source, filename=hooks_path)
		for node in ast.walk(tree):
			if not isinstance(node, ast.Assign):
				continue
			for target in node.targets:
				if not (isinstance(target, ast.Name) and target.id in HOOK_KEYS):
					continue
				try:
					out[target.id] = ast.literal_eval(node.value)
				except (ValueError, TypeError):
					pass
	except SyntaxError:
		pass  # a hooks.py that does not parse is skipped silently
	except Exception:
		frappe.log_error(
			title="Codebase index — hooks.py parse error",
			message=f"File: {hooks_path}\n{frappe.get_traceback()}",
		)
	return out


def _hooks(apps_root: str, installed_apps: list) -> list:
	"""Flatten every installed app's hooks into
	``{hook_type, doctype, event, method, app}`` rows."""
	entries = []
	for app in installed_apps:
		hooks_path = os.path.join(apps_root, app, app, "hooks.py")
		if not os.path.isfile(hooks_path):
			continue
		hooks = _parse_hooks_py(hooks_path)

		# doc_events: {DocType: {event: [method, ...]}}
		for doctype, events in (hooks.get("doc_events") or {}).items():
			if not isinstance(events, dict):
				continue
			for event, methods in events.items():
				if isinstance(methods, str):
					methods = [methods]
				for method in methods or []:
					entries.append({
						"hook_type": "doc_events",
						"doctype": doctype,
						"event": event,
						"method": method,
						"app": app,
					})

		# override_doctype_class: {DocType: 'module.ClassName'}
		for doctype, class_path in (hooks.get("override_doctype_class") or {}).items():
			entries.append({
				"hook_type": "override_doctype_class",
				"doctype": doctype,
				"event": "class_override",
				"method": class_path,
				"app": app,
			})

		# override_whitelisted_methods: {old_path: new_path}
		for old_path, new_path in (hooks.get("override_whitelisted_methods") or {}).items():
			entries.append({
				"hook_type": "override_whitelisted_methods",
				"doctype": "",
				"event": "method_override",
				"method": new_path,
				"app": app,
				"replaces": old_path,
			})

		# scheduler_events: {'daily': [...]} or {'cron': {'expr': [...]}}
		for schedule_type, schedule_data in (hooks.get("scheduler_events") or {}).items():
			if isinstance(schedule_data, list):
				for method in schedule_data:
					entries.append({
						"hook_type": "scheduler_events",
						"doctype": "",
						"event": schedule_type,
						"method": method,
						"app": app,
					})
			elif isinstance(schedule_data, dict):
				for cron_expr, methods in schedule_data.items():
					if isinstance(methods, str):
						methods = [methods]
					for method in methods or []:
						entries.append({
							"hook_type": "scheduler_events",
							"doctype": "",
							"event": f"cron({cron_expr})",
							"method": method,
							"app": app,
						})
	return entries


def build_codebase_index() -> dict:
	"""Build the raw index. Slow; prefer :func:`get_codebase_index`."""
	apps_root = get_apps_root()
	installed_apps = _installed_apps()
	module_app = _module_app_map(apps_root, installed_apps)
	return {
		"apps_root": apps_root,
		"apps_scanned": installed_apps,
		"doctypes": _doctypes(module_app, apps_root),
		"hooks": _hooks(apps_root, installed_apps),
	}


def get_codebase_index() -> dict:
	"""The cached raw index, rebuilt when absent or expired."""
	try:
		cached = frappe.cache.get_value(INDEX_CACHE_KEY)
		if cached:
			return cached
	except Exception:
		pass

	index = build_codebase_index()

	try:
		frappe.cache.set_value(INDEX_CACHE_KEY, index, expires_in_sec=INDEX_TTL)
	except Exception:
		pass  # a cache write failure is not fatal
	return index


def _python_files(apps_root: str, apps) -> list:
	"""``(abs_path, app)`` for each app's api.py files and DocType controllers."""
	pairs = []
	for app in apps or []:
		app_pkg = os.path.join(apps_root, app, app)
		if not os.path.isdir(app_pkg):
			continue
		top_api = os.path.join(app_pkg, "api.py")
		if os.path.isfile(top_api):
			pairs.append((top_api, app))
		for py_path in glob.glob(os.path.join(app_pkg, "*", "api.py")):
			pairs.append((py_path, app))
		for py_path in glob.glob(os.path.join(app_pkg, "**", "doctype", "**", "*.py"), recursive=True):
			pairs.append((py_path, app))
	return pairs


def find_whitelisted_methods(apps, path_keywords=None) -> list:
	"""``@frappe.whitelist()`` functions in ``apps``, as
	``{method, function, file, app, line}`` rows.

	``path_keywords`` keeps the walk cheap on a large bench: a file whose
	relative path contains none of them is skipped without being read. Pass
	None/empty to read every candidate file.
	"""
	apps_root = get_apps_root()
	keywords = {str(k).lower() for k in (path_keywords or []) if str(k).strip()}
	results, seen = [], set()

	for py_path, app in _python_files(apps_root, apps):
		rel_path = os.path.relpath(py_path, apps_root)
		if keywords and not any(kw in rel_path.lower() for kw in keywords):
			continue
		try:
			with open(py_path, encoding="utf-8", errors="ignore") as fh:
				lines = fh.readlines()
		except Exception:
			continue
		if not any(_WHITELIST_DECORATOR in line for line in lines):
			continue

		mod_dotted = rel_path.replace(os.sep, ".").removesuffix(".py")
		for i, line in enumerate(lines):
			if _WHITELIST_DECORATOR not in line.strip():
				continue
			# The decorated def is within a few lines; stacked decorators are
			# skipped over, anything else ends the search for this decorator.
			for j in range(i + 1, min(i + 6, len(lines))):
				candidate = lines[j].strip()
				match = _DEF_RE.match(candidate)
				if match:
					fn_name = match.group(1)
					method = f"{mod_dotted}.{fn_name}"
					if method not in seen:
						seen.add(method)
						results.append({
							"method": method,
							"function": fn_name,
							"file": rel_path,
							"app": app,
							"line": j + 1,
						})
					break
				if candidate and not candidate.startswith("@"):
					break
	return results


_STRUCTURAL_RE = re.compile(
	r"^\s*(if|elif|else|for|while|try|except|finally|return|raise)\b"
	r"|frappe\.throw|frappe\.db\.|frappe\.(get_doc|new_doc|get_all|get_list)\("
	r"|\.(save|insert|submit|cancel|delete)\(|\bself\.\w+\("
)


def _function_info(node, src_lines: list, limit: int) -> dict:
	"""Name, lines and a body without docstring, comments or blanks, cut to ``limit`` lines.

	A body over the limit keeps its def line and the structural lines (control flow, throws,
	database and document calls) so decisions deep inside a long method survive.
	"""
	skip = set()
	first = node.body[0]
	if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
		skip = set(range(first.lineno, first.end_lineno + 1))
	kept = []
	for number in range(node.lineno, node.end_lineno + 1):
		text = src_lines[number - 1].rstrip()
		if number in skip or not text.strip() or text.strip().startswith("#"):
			continue
		kept.append(text)
	full_lines = len(kept)
	if full_lines > limit:
		kept = kept[:1] + [line for line in kept[1:] if _STRUCTURAL_RE.search(line)][: limit - 1]
	return {
		"name": node.name,
		"line": node.lineno,
		"end_line": node.end_lineno,
		"whitelisted": any("frappe.whitelist" in ast.unparse(d) for d in node.decorator_list),
		"body": "\n".join(kept),
		"trimmed": full_lines > limit,
		"full_lines": full_lines,
	}


def _parse_python(abs_path: str):
	"""``(tree, source_lines)`` of a python file."""
	with open(abs_path, encoding="utf-8", errors="ignore") as fh:
		source = fh.read()
	return ast.parse(source, filename=abs_path), source.splitlines()


def _functions_of(body: list, src_lines: list, limit: int) -> list:
	return [
		_function_info(n, src_lines, limit) for n in body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
	]


def _read_controller(abs_path: str, doctype: str, limit: int) -> dict:
	"""The DocType class methods and every module-level function of a controller file."""
	tree, src_lines = _parse_python(abs_path)
	class_name = "".join(word.title() for word in doctype.split())
	classes = [n for n in tree.body if isinstance(n, ast.ClassDef)]
	controller = next((c for c in classes if c.name == class_name), classes[0] if classes else None)
	return {
		"class": controller.name if controller else "",
		"methods": _functions_of(controller.body, src_lines, limit) if controller else [],
		"module_functions": _functions_of(tree.body, src_lines, limit),
	}


def _resolve_dotted(apps_root: str, dotted: str):
	"""``(abs_path, attribute_name)`` for a dotted path from a hooks.py, or ``("", "")``."""
	parts = dotted.split(".")
	if len(parts) < 2:
		return "", ""
	abs_path = os.path.join(apps_root, parts[0], *parts[:-1]) + ".py"
	return (abs_path, parts[-1]) if os.path.isfile(abs_path) else ("", "")


def _module_function(tree, name: str):
	return next((n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name), None)


def _hook_entry(apps_root: str, hook: dict, limit: int) -> dict:
	"""A hook row plus the trimmed body of the function (or override class methods) it names."""
	entry = {key: hook.get(key) for key in ("hook_type", "event", "method", "app")}
	abs_path, name = _resolve_dotted(apps_root, hook.get("method") or "")
	if not abs_path:
		entry["message"] = "source file not found"
		return entry
	tree, src_lines = _parse_python(abs_path)
	entry["file"] = os.path.relpath(abs_path, apps_root)
	if hook.get("hook_type") == "override_doctype_class":
		node = next((n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == name), None)
		entry["methods"] = _functions_of(node.body, src_lines, limit) if node else []
		return entry
	node = _module_function(tree, name)
	if node is None:
		entry["message"] = "function not found in file"
		return entry
	entry.update(_function_info(node, src_lines, limit))
	return entry


def _targets_doctype(apps_root: str, hook: dict, doctype: str, controller_path: str) -> bool:
	"""Whether a scheduler method lives in the DocType's controller or names the DocType."""
	abs_path, name = _resolve_dotted(apps_root, hook.get("method") or "")
	if not abs_path:
		return False
	if abs_path == controller_path:
		return True
	node = _module_function(_parse_python(abs_path)[0], name)
	return node is not None and any(isinstance(n, ast.Constant) and n.value == doctype for n in ast.walk(node))


def read_doctype_sources(doctype_names: list, body_lines: int = 60) -> list:
	"""Controller, hook and scheduler source for each DocType name, as one raw dict each.

	Paths come from the index, never from the name. A DocType without a controller file or
	unknown to the index is reported in ``status`` and ``message``.
	"""
	index = get_codebase_index()
	apps_root = get_apps_root()
	by_name = {dt["name"].lower(): dt for dt in index["doctypes"]}
	out = []
	for requested in doctype_names:
		dt = by_name.get(str(requested).strip().lower())
		if not dt:
			out.append({"doctype": requested, "status": "unknown_doctype", "message": "DocType not found in any installed app"})
			continue
		name = dt["name"]
		if not dt.get("py_exists"):
			out.append({
				"doctype": name,
				"status": "no_controller_file",
				"message": "no controller file in any app (the DocType may be defined in the database only)",
				"hooks": [],
			})
			continue
		controller_path = os.path.join(apps_root, dt["py_file"])
		item = {"doctype": name, "status": "read", "app": dt["app"], "file": dt["py_file"]}
		item.update(_read_controller(controller_path, name, body_lines))
		hooks = [
			h for h in index["hooks"]
			if h.get("doctype") == name and h["hook_type"] in ("doc_events", "override_doctype_class")
		]
		hooks += [
			h for h in index["hooks"]
			if h["hook_type"] == "scheduler_events" and _targets_doctype(apps_root, h, name, controller_path)
		]
		item["hooks"] = [_hook_entry(apps_root, h, body_lines) for h in hooks]
		item["star_hooks"] = sum(1 for h in index["hooks"] if h.get("doctype") == "*")
		out.append(item)
	return out
