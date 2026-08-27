# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""
Filesystem, Node and delivery primitives for the Frontend Agent.

WHY THIS IS A MODULE AND NOT A SERVER SCRIPT
--------------------------------------------
Agent tools are Server Scripts on an ad-hoc "Tools" sub-process, and every BPMN
Script Task passes ``one_bpmn.security.script_validator.deep_inspect_script``
before it can be saved or deployed. That gate permanently forbids ``os``,
``glob``, ``pathlib``, ``subprocess``, ``requests`` and the ``open()`` builtin —
so a script cannot read a file, run prettier, run a build, or open a pull
request. All of that lives here, and the tool script owns everything else.

Same split as ``agents/codebase_index.py`` and ``connectors/handler_authoring.py``:
this module returns RAW results — file text, match lists, build output, screen
findings. It holds no narrative, no ranking and no decision about what to do
next. That is the agent's job and it belongs in the map.

EVERY CHANGE IS A PULL REQUEST
------------------------------
The agent never writes to a running site. Not the Vue application, not desk
JavaScript, and not the desk UI records it would be technically able to write
through frappe — a Client Script row takes effect the moment it is saved, with
no diff, no review and no history a reviewer would read. So there is no
"quick" lane: a UI behaviour change is authored as a FILE in the owning app and
delivered as a pull request, exactly as ``handler_authoring`` delivers connector
handlers. That also makes it the app's code rather than one site's private
customisation, which is where it belonged anyway.

The practical consequence is that Lane B — desk JavaScript — has two halves.
A ``.js`` file that nothing registers is inert, so the same pull request must
also carry the ``hooks.py`` entry that wires it up. ``register_hook`` below is
the only thing in this module that may touch a Python file, and it never takes
Python from the agent: it splices one registration into an existing structure
and returns the whole file.

THE BUILD-CHECK HAZARD THAT SHAPES THIS FILE
---------------------------------------------
``spiff/vite.config.js`` points the ``frappe-ui`` buildConfig plugin at the LIVE
asset directory with ``emptyOutDir: true``, and the plugin's ``writeBundle`` then
copies the built ``index.html`` over ``one_bpmn/www/processa/index.html`` — the
shell the running site actually serves. A build started against that config and
failing part-way leaves the SPA empty and the shell stale.

So ``build_check`` never touches the real tree. It assembles a throwaway copy of
the SPA in a temp directory (source copied, ``node_modules`` symlinked), applies
the candidate files there, writes its own Vite config whose every output path is
inside the temp directory, and builds that. Nothing it does can reach
``one_bpmn/public/processa`` or the served shell.

NEVER RAISES
------------
Every public function returns a dict and swallows its own failures, because each
one is called from inside an LLM tool loop where an exception ends the turn
rather than informing it. The ``compile_ir`` contract in
``agents/bpmn_ir_pipeline.py`` is the precedent.
"""

from __future__ import annotations

import ast
import json
import os
import re
import shutil
import subprocess
import tempfile

import frappe

# ── what may be read and written ─────────────────────────────────────────────
#
# An agent that can read any path can read site_config.json. The allow-lists are
# the boundary, and they are extension-based as well as root-based because a
# path check alone would happily hand over a .py or an .env sitting next to a
# component.
READABLE_EXT = frozenset({".vue", ".js", ".ts", ".css", ".scss", ".html", ".json", ".cjs", ".md"})
WRITABLE_EXT = frozenset({".vue", ".js", ".css", ".scss", ".html"})

# Files that are generated, enormous, or none of the agent's business.
EXCLUDED_PARTS = ("node_modules", "/dist/", "/public/processa/", "/public/one_ai/",
                  "__pycache__", "/.git/", "site_config.json")

MAX_READ_BYTES = 400_000
MAX_SEARCH_HITS = 80
BUILD_TIMEOUT = 600
NODE_TIMEOUT = 120

SPA_APP = "one_bpmn"
SPA_DIR = "spiff"

PREFERRED_BASE_BRANCH = "staging"


# ── paths ────────────────────────────────────────────────────────────────────
def apps_root() -> str:
	"""Absolute path to the bench's ``apps/`` directory."""
	return os.path.abspath(os.path.join(frappe.get_app_path("frappe"), "..", ".."))


def spa_root() -> str:
	"""Absolute path to the Processa Vue SPA source root (``one_bpmn/spiff``)."""
	return os.path.join(apps_root(), SPA_APP, SPA_DIR)


def _excluded(abs_path: str) -> bool:
	probe = abs_path.replace(os.sep, "/")
	if not probe.endswith("/"):
		probe += ""
	for part in EXCLUDED_PARTS:
		if part in probe + "/":
			return True
	return False


def resolve(path: str) -> tuple[str, str]:
	"""Resolve a bench-relative path to an absolute one, or explain the refusal.

	Returns ``(abs_path, "")`` when the path is inside ``apps/``, carries a
	readable extension and is not excluded; ``("", reason)`` otherwise. Symlinks
	are resolved BEFORE the containment check — a link pointing out of the tree
	is the obvious way past a prefix test.
	"""
	if not path or not isinstance(path, str):
		return "", "No path was given."
	root = apps_root()
	candidate = os.path.realpath(os.path.join(root, path.lstrip("/")))
	if not candidate.startswith(os.path.realpath(root) + os.sep):
		return "", f"Refusing to touch {path!r}: it resolves outside the apps directory."
	ext = os.path.splitext(candidate)[1].lower()
	if ext not in READABLE_EXT:
		return "", (f"Refusing to touch {path!r}: {ext or 'no extension'} is not a front-end "
		            f"file type. Allowed: {', '.join(sorted(READABLE_EXT))}.")
	if _excluded(candidate):
		return "", f"Refusing to touch {path!r}: it is generated, vendored or out of scope."
	return candidate, ""


def relative(abs_path: str) -> str:
	"""``apps/``-relative form of an absolute path, for reporting and for PRs."""
	return os.path.relpath(abs_path, apps_root()).replace(os.sep, "/")


def app_of(rel_path: str) -> str:
	"""The app a bench-relative path belongs to (``one_bpmn/spiff/src/…`` → one_bpmn)."""
	head = (rel_path or "").lstrip("/").split("/", 1)[0]
	return head


def repo_relative(rel_path: str) -> str:
	"""Path as the app's OWN repository sees it — the app prefix stripped.

	``one_bpmn/spiff/src/views/Home.vue`` is committed at ``spiff/src/views/Home.vue``.
	"""
	parts = (rel_path or "").lstrip("/").split("/", 1)
	return parts[1] if len(parts) == 2 else rel_path


# ── reading ──────────────────────────────────────────────────────────────────
def read_source(path: str, start: int = 0, end: int = 0) -> dict:
	"""Read a front-end source file, optionally a line range (1-indexed, inclusive)."""
	abs_path, refusal = resolve(path)
	if refusal:
		return {"ok": False, "error": refusal}
	if not os.path.isfile(abs_path):
		return {"ok": False, "error": f"{path} does not exist."}
	try:
		size = os.path.getsize(abs_path)
		with open(abs_path, "r", encoding="utf-8", errors="replace") as fh:
			text = fh.read(MAX_READ_BYTES)
	except Exception as exc:  # noqa: BLE001
		return {"ok": False, "error": f"Could not read {path}: {exc}"}

	lines = text.splitlines()
	total = len(lines)
	sliced = False
	if start or end:
		lo = max(1, int(start or 1))
		hi = min(total, int(end or total))
		if lo > total:
			return {"ok": False, "error": f"{path} has {total} lines; start={lo} is past the end."}
		lines = lines[lo - 1:hi]
		sliced = True
		first = lo
	else:
		first = 1
		if total > 900:
			lines = lines[:900]
			sliced = True

	return {
		"ok": True,
		"path": relative(abs_path),
		"total_lines": total,
		"first_line": first,
		"content": "\n".join(lines),
		"truncated": sliced or size > MAX_READ_BYTES,
	}


def _walk(roots, exts) -> list:
	found = []
	for root in roots:
		if not os.path.isdir(root):
			continue
		for dirpath, dirnames, filenames in os.walk(root):
			dirnames[:] = [d for d in dirnames
			               if d not in ("node_modules", "__pycache__", ".git", "dist")]
			if _excluded(dirpath + "/"):
				continue
			for fn in filenames:
				if os.path.splitext(fn)[1].lower() in exts:
					found.append(os.path.join(dirpath, fn))
	return found


def search_frontend(pattern: str, apps=None, exts=None, limit: int = MAX_SEARCH_HITS) -> dict:
	"""Literal, case-insensitive search across front-end sources.

	Deliberately literal rather than regex: the caller is a language model, a bad
	pattern costs a tool turn, and every search this agent needs is for a name.
	"""
	if not pattern or len(pattern) < 3:
		return {"ok": False, "error": "Give a search string of at least 3 characters."}

	root = apps_root()
	if isinstance(apps, str):
		apps = [a.strip() for a in apps.split(",") if a.strip()]
	apps = apps or ["one_bpmn", "one_fm", "onefm_mcp", "frappe_agile"]
	roots = [os.path.join(root, a) for a in apps if "/" not in a and ".." not in a]

	if isinstance(exts, str):
		exts = [e.strip() for e in exts.split(",") if e.strip()]
	exts = frozenset(e if e.startswith(".") else "." + e
	                 for e in (exts or [".vue", ".js", ".html", ".css", ".scss"]))
	exts = exts & READABLE_EXT

	needle = pattern.lower()
	hits, scanned, capped = [], 0, False
	for abs_path in _walk(roots, exts):
		scanned += 1
		try:
			with open(abs_path, "r", encoding="utf-8", errors="replace") as fh:
				for n, line in enumerate(fh, 1):
					if needle in line.lower():
						hits.append({
							"path": relative(abs_path),
							"line": n,
							"text": line.strip()[:220],
						})
						if len(hits) >= limit:
							capped = True
							break
		except Exception:  # noqa: BLE001 — an unreadable file is not a failed search
			continue
		if capped:
			break

	return {"ok": True, "pattern": pattern, "files_scanned": scanned,
	        "hit_count": len(hits), "hits": hits, "truncated": capped}


# ── locating a screen ────────────────────────────────────────────────────────
def _doctype_script_paths(doctype: str) -> list:
	"""Own-DocType client controllers: ``<app>/<module>/doctype/<snake>/<snake>.js``."""
	snake = frappe.scrub(doctype)
	out = []
	for abs_path in _walk([apps_root()], frozenset({".js"})):
		base = os.path.basename(abs_path)
		if base in (f"{snake}.js", f"{snake}_list.js", f"{snake}_tree.js", f"{snake}_calendar.js"):
			if f"/doctype/{snake}/" in abs_path.replace(os.sep, "/"):
				out.append(relative(abs_path))
	return out


def _hook_entries(doctype: str) -> list:
	"""``doctype_js`` / ``doctype_list_js`` registrations pointing at this DocType."""
	from one_bpmn.agents import codebase_index

	out = []
	root = apps_root()
	try:
		apps = frappe.get_installed_apps()
	except Exception:  # noqa: BLE001
		apps = ["one_fm", "one_bpmn", "hrms", "erpnext"]
	for app in apps:
		hooks_path = os.path.join(root, app, app, "hooks.py")
		if not os.path.isfile(hooks_path):
			continue
		try:
			with open(hooks_path, "r", encoding="utf-8", errors="replace") as fh:
				src = fh.read()
		except Exception:  # noqa: BLE001
			continue
		for hook in ("doctype_js", "doctype_list_js", "doctype_tree_js", "doctype_calendar_js"):
			for match in re.finditer(
				rf'{hook}\s*=\s*\{{(.*?)\n\}}', src, re.S
			):
				for entry in re.finditer(
					rf'["\']{re.escape(doctype)}["\']\s*:\s*\[?\s*["\']([^"\']+)["\']',
					match.group(1),
				):
					out.append({"app": app, "hook": hook, "file": entry.group(1)})
	_ = codebase_index  # imported for parity with the read-primitive family
	return out


def locate_ui(target: str) -> dict:
	"""Every artefact that renders ``target`` — a DocType name or a route path.

	Frappe's front end is scattered by design: the same screen can be shaped by a
	file in an app, a hook registering it, a Client Script row, a pile of Property
	Setters and a List View Settings record. An agent that edits only the file it
	guessed first will produce a change that does nothing, which is the
	characteristic failure in this codebase. This is the tool that prevents it.
	"""
	target = (target or "").strip()
	if not target:
		return {"ok": False, "error": "Name a DocType or a route to locate."}

	found = {"ok": True, "target": target, "kind": None}

	if target.startswith("/") or target.startswith("processa"):
		found["kind"] = "route"
		route = target.lstrip("/")
		found["router_entries"] = []
		router = os.path.join(spa_root(), "src", "router", "index.js")
		if os.path.isfile(router):
			try:
				with open(router, "r", encoding="utf-8", errors="replace") as fh:
					src = fh.read()
				for block in re.finditer(r"\{[^{}]*path:\s*\"([^\"]+)\"[^{}]*\}", src, re.S):
					if route.split("/")[0] in block.group(1):
						found["router_entries"].append(
							{"path": block.group(1), "entry": block.group(0)[:400]}
						)
			except Exception:  # noqa: BLE001
				pass
		found["route_rules"] = []
		hooks_path = os.path.join(apps_root(), SPA_APP, SPA_APP, "hooks.py")
		if os.path.isfile(hooks_path):
			try:
				with open(hooks_path, "r", encoding="utf-8", errors="replace") as fh:
					hsrc = fh.read()
				for rule in re.finditer(r'\{"from_route":\s*"([^"]+)",\s*"to_route":\s*"([^"]+)"\}', hsrc):
					found["route_rules"].append({"from": rule.group(1), "to": rule.group(2)})
			except Exception:  # noqa: BLE001
				pass
		found["www_pages"] = [
			relative(p) for p in _walk(
				[os.path.join(apps_root(), a, a, "www") for a in ("one_bpmn", "one_fm")],
				frozenset({".html"}),
			)
		][:40]
		return found

	# Otherwise treat it as a DocType.
	found["kind"] = "doctype"
	exists = False
	try:
		exists = bool(frappe.db.exists("DocType", target))
	except Exception:  # noqa: BLE001
		pass
	found["doctype_exists"] = exists
	if not exists:
		found["note"] = (
			f"No DocType named {target!r}. Check the spelling, or pass a route "
			f"beginning with '/' if you meant an SPA screen."
		)

	found["controllers"] = _doctype_script_paths(target)
	found["hook_registrations"] = _hook_entries(target)

	# The DocType's own controller decides whose app this screen really belongs to,
	# and therefore whether it may be edited in place or must be customised from
	# one_fm. Saying so here means the agent knows the route before it writes,
	# rather than being refused after it has drafted the wrong file.
	owning_app = ""
	for controller in found["controllers"]:
		owning_app = app_of(controller)
		break
	if not owning_app:
		try:
			module = frappe.db.get_value("DocType", target, "module")
			owning_app = frappe.db.get_value("Module Def", module, "app_name") or ""
		except Exception:  # noqa: BLE001
			owning_app = ""
	if owning_app:
		found["owning_app"] = owning_app
		found["where_to_change"] = change_route(owning_app, target)

	try:
		found["client_scripts"] = frappe.get_all(
			"Client Script", filters={"dt": target},
			fields=["name", "view", "enabled"], limit_page_length=20,
		)
		found["property_setters"] = frappe.db.count("Property Setter", {"doc_type": target})
		found["custom_fields"] = frappe.db.count("Custom Field", {"dt": target})
		found["list_view_settings"] = bool(frappe.db.exists("List View Settings", target))
		found["workspace_links"] = [
			r.parent for r in frappe.get_all(
				"Workspace Link", filters={"link_to": target, "link_type": "DocType"},
				fields=["parent"], limit_page_length=20,
			)
		]
	except Exception as exc:  # noqa: BLE001
		found["db_lookup_error"] = str(exc)[:300]

	return found


# ── what may be used ─────────────────────────────────────────────────────────
def component_catalogue() -> dict:
	"""frappe-ui components, local SPA components, and the Tailwind token source.

	The most common way an LLM breaks a Vue build here is importing a component
	that does not exist. This is the answer to "what may I use?", read from the
	installed package rather than from memory.
	"""
	out = {"ok": True, "frappe_ui": [], "local": [], "tailwind_config": "", "icons": ""}
	fui = os.path.join(spa_root(), "node_modules", "frappe-ui", "src", "components")
	if os.path.isdir(fui):
		names = set()
		for entry in sorted(os.listdir(fui)):
			stem = entry[:-4] if entry.endswith(".vue") else entry
			if stem and stem[0].isupper():
				names.add(stem)
		out["frappe_ui"] = sorted(names)
	try:
		pkg = os.path.join(spa_root(), "node_modules", "frappe-ui", "package.json")
		with open(pkg, "r", encoding="utf-8") as fh:
			out["frappe_ui_version"] = json.load(fh).get("version")
	except Exception:  # noqa: BLE001
		out["frappe_ui_version"] = None

	dts = os.path.join(spa_root(), "components.d.ts")
	if os.path.isfile(dts):
		try:
			with open(dts, "r", encoding="utf-8", errors="replace") as fh:
				body = fh.read()
			out["local"] = sorted(set(re.findall(r"^\s{4}(\w+):", body, re.M)))
		except Exception:  # noqa: BLE001
			pass

	tw = os.path.join(spa_root(), "tailwind.config.cjs")
	if os.path.isfile(tw):
		try:
			with open(tw, "r", encoding="utf-8", errors="replace") as fh:
				out["tailwind_config"] = fh.read()[:6000]
		except Exception:  # noqa: BLE001
			pass

	out["icons"] = ("Lucide, via unplugin-icons: import LucideCheck from '~icons/lucide/check'. "
	                "No other icon library may be added.")
	out["data_access"] = ("Use frappeRequest from 'frappe-ui' (196 call sites) or call(). "
	                      "Do not introduce fetch or axios.")
	return out


# ── screening and the house rubric ───────────────────────────────────────────
#
# screen_markup is a deliberately NARROW malicious-construct check, the same
# posture as handler_authoring.screen_code: it screens for constructs that turn a
# UI change into an attack, not for whether the component is any good. Judging
# quality is the reviewer's job, which is why this ships a pull request.
_MALICE = (
	(r"\beval\s*\(", "eval() — never in front-end source here."),
	(r"\bnew\s+Function\s*\(", "new Function() builds code at runtime."),
	(r"\bdocument\.write\s*\(", "document.write() replaces the document."),
	(r"\.innerHTML\s*=", "innerHTML assignment — build nodes or use a template."),
	(r"\bv-html\b", "v-html renders unescaped markup; use interpolation."),
	(r"<script[^>]*\bsrc\s*=\s*[\"']https?://", "remote <script src> — nothing loads from off-site."),
	(r"\bfetch\s*\(\s*[\"']https?://", "fetch() to an absolute external URL."),
	(r"\bXMLHttpRequest\b", "raw XMLHttpRequest — use frappeRequest."),
	(r"\blocalStorage\.setItem\s*\(\s*[\"'][^\"']*(token|secret|password|key)",
	 "storing a credential in localStorage."),
	(r"(?i)\b(api[_-]?key|api[_-]?secret|password|access[_-]?token)\s*[:=]\s*[\"'][^\"']{8,}",
	 "a hardcoded credential."),
	(r"\bdangerouslySetInnerHTML\b", "dangerouslySetInnerHTML."),
)


def screen_markup(code: str, path: str = "") -> list:
	"""Malicious or credential-leaking constructs in generated front-end source."""
	findings = []
	for pattern, message in _MALICE:
		for match in re.finditer(pattern, code or ""):
			line = (code or "").count("\n", 0, match.start()) + 1
			findings.append(f"{path or 'source'}:{line} — {message}")
	return findings


def rubric_check(code: str, path: str = "") -> list:
	"""The mechanical half of ``.github/instructions/vue-frontend.instructions.md``.

	The house rubric is already written; this is what makes it enforceable before
	a reviewer ever sees the diff. It reports only what can be decided by reading
	the file — component size, banned constructs, missing keys, raw colours. Taste
	is not in here and should not be.
	"""
	findings = []
	code = code or ""
	is_vue = path.endswith(".vue")

	if is_vue:
		setup = re.search(r"<script\s+setup[^>]*>(.*?)</script>", code, re.S)
		if not setup and "<script" in code:
			findings.append(f"{path}: uses the Options API. Components here must use <script setup>.")
		if setup:
			n = setup.group(1).count("\n")
			if n > 300:
				findings.append(
					f"{path}: <script setup> is {n} lines (limit 300). Extract a composable "
					f"or split the component."
				)
		if re.search(r"<[^>]*\bv-for\b[^>]*\bv-if\b|<[^>]*\bv-if\b[^>]*\bv-for\b", code):
			findings.append(f"{path}: v-if and v-for on the same element.")
		for match in re.finditer(r"<([a-zA-Z][\w.-]*)([^>]*\bv-for\b[^>]*)>", code):
			if ":key" not in match.group(2) and "v-bind:key" not in match.group(2):
				line = code.count("\n", 0, match.start()) + 1
				findings.append(f"{path}:{line} — v-for on <{match.group(1)}> without :key.")

	for match in re.finditer(r"#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})\b", code):
		line = code.count("\n", 0, match.start()) + 1
		findings.append(
			f"{path}:{line} — hardcoded colour {match.group(0)}. Use a Tailwind token."
		)

	for tag, replacement in (("select", "FormControl type=\"select\""),
	                         ("button", "Button"),
	                         ("dialog", "Dialog")):
		for match in re.finditer(rf"<{tag}\b(?![^>]*\bis\b)", code):
			line = code.count("\n", 0, match.start()) + 1
			findings.append(
				f"{path}:{line} — raw <{tag}>. Use frappe-ui {replacement}."
			)

	for match in re.finditer(r"\bfunction\s+\w+\s*\([^)]*\)\s*\{", code):
		tail = code[match.end():]
		depth, length = 1, 0
		for ch in tail:
			length += 1
			if ch == "{":
				depth += 1
			elif ch == "}":
				depth -= 1
				if depth == 0:
					break
		if tail[:length].count("\n") > 30:
			line = code.count("\n", 0, match.start()) + 1
			findings.append(f"{path}:{line} — function is over 30 lines. Extract a helper.")

	if re.search(r"\.on\(|addEventListener\(", code) and "onBeforeUnmount" not in code:
		findings.append(
			f"{path}: registers listeners but never cleans up in onBeforeUnmount."
		)

	return findings[:40]


def screen_review(path: str, content: str) -> dict:
	"""Screening findings split into what this change INTRODUCES and what was already there.

	Same reasoning as ``rubric_review``, and it matters more here because screening
	*blocks*. ``one_fm/public/js/doctype_js/vehicle.js`` already contains
	``document.write`` and an ``innerHTML`` assignment in a QR-code helper, so an
	absolute screen refused to let the agent add an unrelated indicator to that file
	until it had rewritten legacy code it was never asked to touch — observed live,
	two wasted drafts. Whole swathes of one_fm would be uneditable on the same
	grounds.

	Blocking on what the change adds is also the stronger rule, not the weaker one:
	anything the agent writes is judged, and what it did not write was already in
	the repository and reviewed by whoever put it there. Pre-existing findings are
	still reported so the pull request can mention them.
	"""
	current = screen_markup(content or "", path)
	baseline = []
	abs_path, refusal = resolve(path)
	if not refusal and os.path.isfile(abs_path):
		try:
			with open(abs_path, "r", encoding="utf-8", errors="replace") as fh:
				baseline = screen_markup(fh.read(), path)
		except Exception:  # noqa: BLE001 — an unreadable original means judge it whole
			baseline = []

	remaining = {}
	for finding in baseline:
		key = _finding_key(finding)
		remaining[key] = remaining.get(key, 0) + 1

	introduced, pre_existing = [], []
	for finding in current:
		key = _finding_key(finding)
		if remaining.get(key):
			remaining[key] -= 1
			pre_existing.append(finding)
		else:
			introduced.append(finding)

	return {"introduced": introduced, "pre_existing": pre_existing}


def _finding_key(finding: str) -> str:
	"""A finding stripped of its line number, so it survives lines moving."""
	return re.sub(r":\d+\s+—", " —", finding)


def rubric_review(path: str, content: str) -> dict:
	"""Rubric findings split into what this change INTRODUCES and what was already there.

	Blocking on everything a file contains makes any edit to an old file drag in
	unrelated cleanup. Observed on the first real run: asked to add one option to a
	dropdown, the agent also rewrote three scrollbar colours and extracted a helper
	function, because the rubric flagged violations that pre-dated its change and it
	could not tell the difference. The diff stopped being the change that was asked
	for, which is exactly the sprawl the house rules forbid.

	So a change is judged on what it does. Pre-existing findings are still reported —
	someone may want them fixed — but they do not block delivery.
	"""
	current = rubric_check(content or "", path)
	baseline = []
	abs_path, refusal = resolve(path)
	if not refusal and os.path.isfile(abs_path):
		try:
			with open(abs_path, "r", encoding="utf-8", errors="replace") as fh:
				baseline = rubric_check(fh.read(), path)
		except Exception:  # noqa: BLE001 — an unreadable original means judge it whole
			baseline = []

	remaining = {}
	for finding in baseline:
		key = _finding_key(finding)
		remaining[key] = remaining.get(key, 0) + 1

	introduced, pre_existing = [], []
	for finding in current:
		key = _finding_key(finding)
		if remaining.get(key):
			remaining[key] -= 1
			pre_existing.append(finding)
		else:
			introduced.append(finding)

	return {"introduced": introduced, "pre_existing": pre_existing}


# ── node-backed checks ───────────────────────────────────────────────────────
def _node() -> str:
	found = shutil.which("node")
	if found:
		return found
	for candidate in ("/usr/bin/node", "/usr/local/bin/node"):
		if os.path.isfile(candidate):
			return candidate
	return ""


def _run(cmd, cwd, timeout, stdin_text=None) -> dict:
	"""Run a child process and always return a dict — never raise into a tool loop."""
	try:
		proc = subprocess.run(
			cmd, cwd=cwd, input=stdin_text, capture_output=True, text=True, timeout=timeout,
		)
		return {"ok": proc.returncode == 0, "code": proc.returncode,
		        "stdout": proc.stdout or "", "stderr": proc.stderr or ""}
	except subprocess.TimeoutExpired:
		return {"ok": False, "code": -1, "stdout": "", "stderr": f"timed out after {timeout}s"}
	except Exception as exc:  # noqa: BLE001
		return {"ok": False, "code": -1, "stdout": "", "stderr": str(exc)}


def format_source(path: str, content: str) -> dict:
	"""Run prettier over candidate content, returning the formatted text.

	pre-commit runs prettier over ``javascript, vue, scss`` and CI fails the pull
	request when it would change anything. Formatting here removes a whole class
	of red PRs before one exists.
	"""
	prettier = os.path.join(spa_root(), "node_modules", ".bin", "prettier")
	if not os.path.isfile(prettier):
		return {"ok": False, "error": "prettier is not installed in spiff/node_modules.",
		        "content": content}
	res = _run([prettier, "--stdin-filepath", path or "component.vue"],
	           cwd=spa_root(), timeout=NODE_TIMEOUT, stdin_text=content or "")
	if not res["ok"]:
		return {"ok": False, "error": (res["stderr"] or "prettier failed")[:1200],
		        "content": content}
	formatted = res["stdout"]
	return {"ok": True, "changed": formatted != (content or ""), "content": formatted}


_CHECK_CONFIG = """\
import vue from "@vitejs/plugin-vue"
import frappeui from "frappe-ui/vite"
import path from "path"
import { defineConfig } from "vite"

// Generated by one_bpmn.frontend.authoring.build_check — every output path is
// inside this temporary directory. It deliberately does NOT import the project's
// vite.config.js, whose buildConfig plugin is bound to the live asset directory.
export default defineConfig({
  plugins: [
    frappeui({
      frappeProxy: false,
      lucideIcons: true,
      jinjaBootData: true,
      buildConfig: {
        outDir: __OUT__,
        emptyOutDir: true,
        sourcemap: false,
        indexHtmlPath: __SHELL__,
      },
    }),
    vue(),
  ],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "src"),
      "preact/hooks": path.resolve(__dirname, "node_modules/preact/hooks"),
      "preact": path.resolve(__dirname, "node_modules/preact"),
    },
    dedupe: [
      "@bpmn-io/properties-panel", "preact", "preact/hooks", "preact/compat",
      "diagram-js", "dmn-js-shared", "inferno",
    ],
  },
  optimizeDeps: {
    include: ["feather-icons", "bpmnlint", "bpmnlint-utils", "dmn-js/lib/Modeler"],
  },
  build: {
    sourcemap: false,
    chunkSizeWarningLimit: 1500,
    rollupOptions: { input: __INPUT__ },
  },
  logLevel: "warn",
})
"""

# A component nobody imports yet is not in the entry graph, so Vite never
# compiles it and the build passes while the file is broken — observed: a
# component importing a non-existent module built clean. Every candidate file is
# therefore pulled in through a generated probe entry, so the check reports on
# what the agent actually wrote rather than only on what the app already reached.
_PROBE = "src/__candidate_probe.js"

_COPY_ENTRIES = ("src", "index.html", "tailwind.config.cjs", "postcss.config.cjs",
                 "package.json", "components.d.ts", "auto-imports.d.ts")


def build_check(files: dict | None = None) -> dict:
	"""Compile the SPA with ``files`` applied, in a throwaway copy of the tree.

	``files`` maps SPA-relative paths (``src/views/Thing.vue``) to their full new
	content. Pass none to check the tree as it stands.

	Returns ``{ok, errors, warnings, duration_s, output}``. A failing build is a
	result, not an exception — the agent is expected to read the errors and try
	again.
	"""
	node = _node()
	if not node:
		return {"ok": False, "errors": ["node was not found on PATH."], "warnings": [],
		        "duration_s": 0, "output": ""}

	src_root = spa_root()
	if not os.path.isdir(os.path.join(src_root, "node_modules")):
		return {"ok": False, "errors": ["spiff/node_modules is missing — run yarn install."],
		        "warnings": [], "duration_s": 0, "output": ""}

	tmp = tempfile.mkdtemp(prefix="fe_build_")
	try:
		work = os.path.join(tmp, "spa")
		os.makedirs(work)
		for entry in _COPY_ENTRIES:
			source = os.path.join(src_root, entry)
			if not os.path.exists(source):
				continue
			target = os.path.join(work, entry)
			if os.path.isdir(source):
				shutil.copytree(source, target, symlinks=True)
			else:
				shutil.copy2(source, target)
		os.symlink(os.path.join(src_root, "node_modules"), os.path.join(work, "node_modules"))

		applied = []
		for rel, content in (files or {}).items():
			safe = os.path.realpath(os.path.join(work, str(rel).lstrip("/")))
			if not safe.startswith(os.path.realpath(work) + os.sep):
				return {"ok": False, "errors": [f"Refusing to place {rel!r} outside the build copy."],
				        "warnings": [], "duration_s": 0, "output": ""}
			os.makedirs(os.path.dirname(safe), exist_ok=True)
			with open(safe, "w", encoding="utf-8") as fh:
				fh.write(content or "")
			applied.append(str(rel))

		# Force every candidate through the compiler, reachable or not.
		inputs = {"index": os.path.join(work, "index.html")}
		probe_imports = [
			f"import {json.dumps('./' + os.path.relpath(p, 'src').replace(os.sep, '/'))}"
			for p in applied
			if p.startswith("src/") and os.path.splitext(p)[1] in (".vue", ".js", ".ts")
		]
		if probe_imports:
			probe_path = os.path.join(work, _PROBE)
			os.makedirs(os.path.dirname(probe_path), exist_ok=True)
			with open(probe_path, "w", encoding="utf-8") as fh:
				fh.write("// generated by build_check — forces candidate files into the graph\n")
				fh.write("\n".join(probe_imports) + "\n")
			inputs["candidate_probe"] = probe_path

		out_dir = os.path.join(tmp, "out")
		shell = os.path.join(tmp, "shell.html")
		config_path = os.path.join(work, "vite.check.config.js")
		with open(config_path, "w", encoding="utf-8") as fh:
			fh.write(
				_CHECK_CONFIG
				.replace("__OUT__", json.dumps(out_dir))
				.replace("__SHELL__", json.dumps(shell))
				.replace("__INPUT__", json.dumps(inputs))
			)

		import time

		started = time.monotonic()
		env = dict(os.environ, NODE_OPTIONS="--max-old-space-size=8192", CI="1")
		proc = subprocess.run(
			[node, os.path.join(src_root, "node_modules", "vite", "bin", "vite.js"),
			 "build", "--config", config_path],
			cwd=work, capture_output=True, text=True, timeout=BUILD_TIMEOUT, env=env,
		)
		duration = round(time.monotonic() - started, 1)
		combined = (proc.stdout or "") + "\n" + (proc.stderr or "")

		errors, warnings = [], []
		for line in combined.splitlines():
			stripped = line.strip()
			if not stripped:
				continue
			low = stripped.lower()
			if low.startswith("error") or "rolluperror" in low or "[vite]: rollup failed" in low:
				errors.append(stripped[:400])
			elif low.startswith("warning") or low.startswith("[warning]"):
				warnings.append(stripped[:300])
		if proc.returncode != 0 and not errors:
			errors = [ln[:400] for ln in combined.splitlines() if ln.strip()][-12:]

		return {
			"ok": proc.returncode == 0,
			"applied": applied,
			"errors": errors[:20],
			"warnings": warnings[:15],
			"duration_s": duration,
			"output": combined[-4000:],
		}
	except subprocess.TimeoutExpired:
		return {"ok": False, "errors": [f"The build did not finish within {BUILD_TIMEOUT}s."],
		        "warnings": [], "duration_s": BUILD_TIMEOUT, "output": ""}
	except Exception as exc:  # noqa: BLE001
		return {"ok": False, "errors": [str(exc)[:600]], "warnings": [],
		        "duration_s": 0, "output": ""}
	finally:
		shutil.rmtree(tmp, ignore_errors=True)


# ── which app a change belongs in ────────────────────────────────────────────
#
# The bench holds two kinds of app and they are changed in opposite ways.
#
# Ours (one_fm, one_bpmn, onefm_mcp, frappe_agile, onefm_sso …) are ours to edit:
# the change goes in the file that already renders the screen, and the pull
# request goes to that app's own repository.
#
# Upstream apps (frappe, erpnext, hrms, helpdesk, payments, lending, wiki …) are
# NOT. Editing them would put internal work in someone else's pull request queue
# and be wiped by the next upgrade. Frappe's own answer is the customisation app:
# leave the upstream file alone and add a script in one_fm, registered against
# the upstream DocType through a ``doctype_js`` hook. one_fm already does exactly
# this for roughly fifty ERPNext and HRMS DocTypes, so the agent is following a
# path the codebase has already worn.
#
# Ownership is read off the git remote rather than hardcoded, so a fork or a
# renamed organisation needs no code change here — the same basis
# ``production_review._allowed_repo_owners`` already uses.
_REPO_CACHE: dict = {}


def customization_app() -> str:
	"""The app that carries customisations of upstream DocTypes."""
	configured = (frappe.get_cached_value("Processa Settings", None, "customization_app") or "").strip()
	return configured or "one_fm"


def _repo_of(app: str) -> str | None:
	if app not in _REPO_CACHE:
		from one_bpmn.api.production_review import _repo_for_app

		try:
			_REPO_CACHE[app] = _repo_for_app(app)
		except Exception:  # noqa: BLE001
			_REPO_CACHE[app] = None
	return _REPO_CACHE[app]


def app_ownership(app: str) -> dict:
	"""Whether ``app`` is one we may open a pull request against."""
	from one_bpmn.api.production_review import _allowed_repo_owners

	repo = _repo_of(app)
	if not repo:
		return {"app": app, "owned": False, "repo": None,
		        "reason": f"No git remote resolves for {app!r}, so there is nowhere to deliver."}
	owner = repo.split("/")[0]
	try:
		allowed = {o.lower() for o in (_allowed_repo_owners() or ())}
	except Exception:  # noqa: BLE001
		allowed = set()
	owned = bool(allowed) and owner.lower() in allowed
	return {
		"app": app, "owned": owned, "repo": repo, "owner": owner,
		"reason": "" if owned else (
			f"{app} belongs to {owner}, not to us. Upstream code is not ours to change and "
			f"an upgrade would overwrite it anyway."
		),
	}


def change_route(target_app: str, doctype: str = "") -> dict:
	"""Where a change aimed at ``target_app`` must actually be made.

	Returns ``route`` = ``in_place`` when the app is ours, or ``customisation``
	when it is upstream — in which case ``app``, ``file`` and ``hook`` describe the
	script to write in the customisation app instead.
	"""
	own = app_ownership(target_app)
	if own["owned"]:
		return {"route": "in_place", "app": target_app, "repo": own["repo"],
		        "note": f"{target_app} is ours — change the file that already renders this."}

	host = customization_app()
	host_own = app_ownership(host)
	route = {
		"route": "customisation",
		"app": host,
		"repo": host_own.get("repo"),
		"why": own["reason"],
		"note": (
			f"Do not edit {target_app}. Add the behaviour in {host} and register it against "
			f"the {target_app} DocType, which is how {host} already customises upstream apps."
		),
	}
	if doctype:
		snake = frappe.scrub(doctype)
		route["file"] = f"{host}/{host}/public/js/doctype_js/{snake}.js"
		route["hook"] = {"app": host, "hook": "doctype_js", "key": doctype,
		                 "file": f"public/js/doctype_js/{snake}.js"}
	return route


# ── wiring a desk script up ──────────────────────────────────────────────────
#
# Only these hooks, and only ever a path inside the app's own public/js. The
# agent supplies a DocType (or page) and a file it has already staged; it never
# supplies Python. Anything else is a different kind of change and belongs to a
# person.
DICT_HOOKS = ("doctype_js", "doctype_list_js", "doctype_tree_js", "doctype_calendar_js", "page_js")
LIST_HOOKS = ("app_include_js", "app_include_css", "web_include_js", "web_include_css")


def hooks_path(app: str) -> str:
	"""Bench-relative path of an app's hooks.py."""
	return f"{app}/{app}/hooks.py"


def _matching_brace(text: str, open_idx: int) -> int:
	"""Index just past the brace/bracket that closes the one at ``open_idx``."""
	opener = text[open_idx]
	closer = {"{": "}", "[": "]"}[opener]
	depth, i = 0, open_idx
	for i in range(open_idx, len(text)):
		ch = text[i]
		if ch == opener:
			depth += 1
		elif ch == closer:
			depth -= 1
			if depth == 0:
				return i
	return -1


def register_hook(app: str, hook: str, key: str, file_path: str,
                  current: str | None = None) -> dict:
	"""Splice one registration into ``app``'s hooks.py and return the whole file.

	``key`` is the DocType or page name for a dict hook, and is ignored for a list
	hook. ``file_path`` is the app-relative path the hook wants — ``public/js/…``
	for a dict hook, ``/assets/<app>/js/…`` for a bundle include.

	Merged, never regenerated, and idempotent: a registration that is already
	there returns the file untouched. The result is parsed before it is returned,
	because a hooks.py that does not import takes the whole app down, not just the
	screen being changed.
	"""
	if hook not in DICT_HOOKS and hook not in LIST_HOOKS:
		return {"ok": False, "error": f"{hook!r} is not a hook this may register. "
		                             f"Allowed: {', '.join(DICT_HOOKS + LIST_HOOKS)}."}
	if not re.fullmatch(r"[a-z][a-z0-9_]*", app or ""):
		return {"ok": False, "error": f"{app!r} is not an app name."}

	path = hooks_path(app)
	if current is None:
		abs_path = os.path.join(apps_root(), path)
		if not os.path.isfile(abs_path):
			return {"ok": False, "error": f"{path} does not exist."}
		try:
			with open(abs_path, "r", encoding="utf-8") as fh:
				current = fh.read()
		except Exception as exc:  # noqa: BLE001
			return {"ok": False, "error": f"Could not read {path}: {exc}"}

	if hook in DICT_HOOKS:
		if not key:
			return {"ok": False, "error": f"{hook} needs the DocType or page it applies to."}
		if not re.fullmatch(r"[\w/ .&'()-]+", key):
			return {"ok": False, "error": f"{key!r} is not a usable {hook} key."}
		if not re.fullmatch(r"public/js/[\w./-]+\.js", file_path or ""):
			return {"ok": False, "error": "A dict hook's file must be an app-relative "
			                              "public/js/….js path."}
		entry = f'\t"{key}": "{file_path}",'
		opener, block = "{", f"{hook} = {{\n{entry}\n}}\n"
	else:
		if not re.fullmatch(r"/assets/[\w./-]+\.(js|css)", file_path or ""):
			return {"ok": False, "error": "An include hook's file must be an "
			                              "/assets/….js or .css path."}
		entry = f'\t"{file_path}",'
		opener, block = "[", f"{hook} = [\n{entry}\n]\n"

	# Already registered? Say so and change nothing.
	assign = re.search(rf"^{re.escape(hook)}\s*=\s*", current, re.M)
	if assign and file_path in current[assign.end():assign.end() + 20000]:
		region_open = current.find(opener, assign.end())
		if region_open != -1:
			region_close = _matching_brace(current, region_open)
			if region_close != -1 and file_path in current[region_open:region_close]:
				return {"ok": True, "path": path, "content": current,
				        "changed": False, "note": "already registered"}

	if not assign:
		# No such hook in this app yet — a whole new block at the end reads better
		# than one wedged between unrelated assignments.
		updated = current.rstrip("\n") + "\n\n" + block
	else:
		region_open = current.find(opener, assign.end())
		if region_open == -1:
			return {"ok": False, "error": f"{hook} in {path} is not a literal "
			                              f"{'dict' if opener == '{' else 'list'}; "
			                              f"a person should wire this one up."}
		region_close = _matching_brace(current, region_open)
		if region_close == -1:
			return {"ok": False, "error": f"{hook} in {path} is not closed; refusing to guess."}
		# Append AFTER the last entry, adding the separating comma when the block
		# does not already end in one. one_fm's doctype_js leaves the last entry
		# bare, so inserting straight before the closing brace produced two entries
		# with nothing between them and a hooks.py that would not import.
		inner_start = region_open + 1
		inner = current[inner_start:region_close]
		body = inner.rstrip()
		insert_at = inner_start + len(body)
		separator = "," if body and not body.endswith(",") else ""
		# Match the indentation the block already uses — one_fm's hooks.py mixes
		# tabs and four spaces, and a line indented differently from its neighbours
		# is the first thing a reviewer's eye catches for no reason.
		last_line = body.rsplit("\n", 1)[-1] if body else ""
		indent = re.match(r"[ \t]*", last_line).group(0) or "\t"
		updated = (current[:insert_at] + separator + "\n" + indent + entry.lstrip("\t")
		           + current[insert_at:])

	try:
		ast.parse(updated)
	except SyntaxError as exc:
		return {"ok": False,
		        "error": f"Splicing that registration would break {path} ({exc}). Nothing changed."}

	return {"ok": True, "path": path, "content": updated, "changed": True,
	        "registered": {"hook": hook, "key": key, "file": file_path}}


# ── delivery ─────────────────────────────────────────────────────────────────
def _base_branch(repo: str, token: str) -> str | None:
	"""Prefer ``staging``; fall back to the repository default when it has none.

	Same reasoning as ``handler_authoring.resolve_base_branch``: house work
	branches off staging, but one_bpmn's DEFAULT branch is version-15, so leaving
	the choice to github_sync would quietly skip staging.
	"""
	from one_bpmn.api.github_sync import branch_exists

	try:
		if branch_exists(token=token, repo=repo, branch=PREFERRED_BASE_BRANCH):
			return PREFERRED_BASE_BRANCH
	except Exception:  # noqa: BLE001
		frappe.log_error(title="Frontend Agent: base branch probe failed",
		                 message=frappe.get_traceback())
	return None


def propose_frontend_pr(*, files: dict, title: str, summary: str,
                        branch_hint: str = "", evidence: dict | None = None) -> dict:
	"""Deliver front-end source changes as a pull request.

	``files`` maps bench-relative paths (``one_bpmn/spiff/src/views/Thing.vue``) to
	their full new content. Every file must belong to the SAME app, because a pull
	request belongs to one repository — a change spanning two apps is two
	deliveries and saying so is more useful than silently dropping half of it.

	The change is never written to this site. CI builds the SPA on merge to
	staging, so a pull request carrying source alone is a complete change.
	"""
	from one_bpmn.api.github_sync import open_customization_pr
	from one_bpmn.api.production_review import _allowed_repo_owners, _repo_for_app

	if not files:
		return {"ok": False, "error": "No files to deliver."}

	prepared, apps = {}, set()
	for rel_path, content in files.items():
		normalised = (rel_path or "").lstrip("/")
		# hooks.py is the one Python file that may travel, and only because
		# register_hook built it: the agent cannot hand over Python of its own.
		# It is re-parsed here rather than trusted, since a broken hooks.py takes
		# down the whole app rather than the screen being changed.
		if normalised.endswith("/hooks.py"):
			owner = app_of(normalised)
			if normalised != hooks_path(owner):
				return {"ok": False,
				        "error": f"Refusing to write {rel_path!r}: the only Python file that "
				                 f"may be delivered is an app's own hooks.py."}
			try:
				ast.parse(content or "")
			except SyntaxError as exc:
				return {"ok": False, "error": f"{normalised} does not parse ({exc})."}
			apps.add(owner)
			prepared[repo_relative(normalised)] = content or ""
			continue

		abs_path, refusal = resolve(rel_path)
		if refusal:
			return {"ok": False, "error": refusal}
		ext = os.path.splitext(abs_path)[1].lower()
		if ext not in WRITABLE_EXT:
			return {"ok": False,
			        "error": f"Refusing to write {rel_path!r}: {ext} is not an editable "
			                 f"front-end file type."}
		# Judged on what the change adds — see screen_review. Everything the agent
		# wrote is still screened; what was already committed is not its doing.
		malice = screen_review(rel_path, content or "")["introduced"]
		if malice:
			return {"ok": False, "error": "Screening refused this change.", "findings": malice}
		normalised = relative(abs_path)
		apps.add(app_of(normalised))
		prepared[repo_relative(normalised)] = content or ""

	if len(apps) > 1:
		return {"ok": False,
		        "error": f"These files span more than one app ({', '.join(sorted(apps))}). "
		                 f"A pull request belongs to one repository — deliver them separately."}

	app = apps.pop()
	# Last line of defence on app routing. draft_change already refuses to stage a
	# file in an upstream app, but delivery is where it would actually do harm, so
	# it is checked again here rather than assumed.
	own = app_ownership(app)
	if not own["owned"]:
		route = change_route(app)
		return {"ok": False, "retryable": False,
		        "error": f"Refusing to open a pull request against {own.get('repo') or app}. "
		                 f"{own['reason']} {route['note']}",
		        "route": route}

	token = frappe.get_cached_doc("Processa Settings").get_password("github_token")
	repo = _repo_for_app(app)
	if not token:
		return {"ok": False, "retryable": False,
		        "error": "No GitHub Access Token is configured in Processa Settings."}
	if not repo:
		return {"ok": False, "retryable": False,
		        "error": f"No git remote resolved for app {app!r}, so there is nowhere to "
		                 f"open the pull request."}

	slug = re.sub(r"[^a-z0-9]+", "-", (branch_hint or title or "change").lower()).strip("-")[:40]
	head = f"frontend-agent/{slug or 'change'}-{frappe.generate_hash(length=6)}"

	body_lines = [summary or "", "", "---", "",
	              "Raised by the **Frontend Agent**. Source only — CI builds the SPA on merge.",
	              "", "**Files**"]
	for path in sorted(prepared):
		body_lines.append(f"- `{path}`")
	if evidence:
		body_lines += ["", "**Checks**"]
		for key in ("build", "prettier", "screening", "rubric"):
			if key in evidence:
				body_lines.append(f"- {key}: {evidence[key]}")
	body_lines += ["", "This change has not been rendered in a browser unless a screenshot "
	                   "is attached above. Review the diff."]

	try:
		url = open_customization_pr(
			token=token,
			repo=repo,
			base_branch=_base_branch(repo, token),
			head_branch=head,
			files=prepared,
			commit_message=f"feat(ui): {title}"[:72],
			pr_title=title,
			pr_body="\n".join(body_lines),
			allowed_owners=_allowed_repo_owners(),
		)
	except Exception as exc:  # noqa: BLE001
		return {"ok": False, "error": str(exc)[:800], "repository": repo}

	return {"ok": True, "pull_request": url, "repository": repo,
	        "branch": head, "files": sorted(prepared), "app": app}
