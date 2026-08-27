# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""
The only things the Frontend Agent cannot do from a Server Script.

WHY THIS MODULE IS AS SMALL AS IT IS
------------------------------------
Every BPMN Script Task passes ``one_bpmn.security.script_validator.deep_inspect_script``,
which permanently forbids ``os``, ``glob``, ``pathlib``, ``subprocess``, ``shutil``,
``tempfile``, ``requests`` and the ``open()`` builtin. That is the ONLY reason
anything here is Python. The test applied to every function below was not "is
this easier in Python" but "does the gate make it impossible in a script" — and
whatever failed that test went back into the tool script, where a process owner
can see and change it.

So this holds no policy. It does not know which file types the agent may edit,
which constructs are forbidden in generated markup, what the house rules are,
which apps are ours, or how a pull request should read. It walks, reads, runs a
child process, and returns raw structure. Same posture as
``agents/codebase_index.py``, and for the same reason: logic that lives in Python
is invisible in the diagram and needs a developer and a deploy to change.

The one exception is ``resolve``. Containment is a security boundary and has to
be decided in one place, atomically, after symlinks are resolved — a script that
assembled the same check out of three primitives could be talked out of one of
them.

NEVER RAISES
------------
Every function returns a dict or a plain value and swallows its own failures.
Each is called from inside an LLM tool loop, where an exception ends the turn
rather than informing it.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile

import frappe

# Bounds, not policy: these stop a single call exhausting memory or wedging the
# worker. What the agent is ALLOWED to touch is decided in the tool scripts.
MAX_READ_BYTES = 400_000
BUILD_TIMEOUT = 600
NODE_TIMEOUT = 120

# Containment. A path that escapes the apps tree, or reaches generated output or
# vendored code, is refused here rather than anywhere else.
READABLE_EXT = frozenset({".vue", ".js", ".ts", ".css", ".scss", ".html", ".json", ".cjs", ".md", ".py"})
EXCLUDED_PARTS = ("node_modules", "/dist/", "/public/processa/", "/public/one_ai/",
                  "__pycache__", "/.git/", "site_config.json")

SPA_APP = "one_bpmn"
SPA_DIR = "spiff"


# ── paths ────────────────────────────────────────────────────────────────────
def apps_root() -> str:
	"""Absolute path to the bench's ``apps/`` directory."""
	return os.path.abspath(os.path.join(frappe.get_app_path("frappe"), "..", ".."))


def spa_root() -> str:
	"""Absolute path to the Processa Vue SPA source root."""
	return os.path.join(apps_root(), SPA_APP, SPA_DIR)


def relative(abs_path: str) -> str:
	"""``apps/``-relative form of an absolute path."""
	return os.path.relpath(abs_path, apps_root()).replace(os.sep, "/")


def resolve(path: str) -> tuple:
	"""Resolve a bench-relative path, or explain the refusal.

	Returns ``(abs_path, "")`` when the path is inside ``apps/``, carries a
	readable extension and is not generated or vendored; ``("", reason)``
	otherwise.

	Symlinks are resolved BEFORE the containment check — a link pointing out of
	the tree is the obvious way past a prefix test. This is the agent's security
	boundary and is deliberately one indivisible function.
	"""
	if not path or not isinstance(path, str):
		return "", "No path was given."
	root = os.path.realpath(apps_root())
	candidate = os.path.realpath(os.path.join(apps_root(), path.lstrip("/")))
	if not candidate.startswith(root + os.sep):
		return "", f"Refusing to touch {path!r}: it resolves outside the apps directory."
	ext = os.path.splitext(candidate)[1].lower()
	if ext not in READABLE_EXT:
		return "", (f"Refusing to touch {path!r}: {ext or 'no extension'} is not a readable "
		            f"file type here.")
	probe = candidate.replace(os.sep, "/") + "/"
	for part in EXCLUDED_PARTS:
		if part in probe:
			return "", f"Refusing to touch {path!r}: it is generated, vendored or out of scope."
	return candidate, ""


def read_text(path: str) -> dict:
	"""Whole-file read, bounded. Slicing and presentation belong to the caller."""
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
	return {"ok": True, "path": relative(abs_path), "content": text,
	        "truncated": size > MAX_READ_BYTES}


def exists(path: str) -> bool:
	abs_path, refusal = resolve(path)
	return bool(not refusal and os.path.isfile(abs_path))


def list_dir(path: str) -> list:
	"""Entry names in a directory under ``apps/``. Empty when it is not there."""
	candidate = os.path.realpath(os.path.join(apps_root(), (path or "").lstrip("/")))
	if not candidate.startswith(os.path.realpath(apps_root()) + os.sep):
		return []
	try:
		return sorted(os.listdir(candidate))
	except Exception:  # noqa: BLE001
		return []


def list_files(apps=None, exts=None, limit: int = 20000) -> list:
	"""Bench-relative paths of files under ``apps`` with one of ``exts``."""
	root = apps_root()
	roots = []
	for app in (apps or []):
		if "/" in app or ".." in app:
			continue
		roots.append(os.path.join(root, app))
	wanted = set()
	for ext in (exts or []):
		wanted.add(ext if ext.startswith(".") else "." + ext)

	found = []
	for base in roots:
		if not os.path.isdir(base):
			continue
		for dirpath, dirnames, filenames in os.walk(base):
			dirnames[:] = [d for d in dirnames
			               if d not in ("node_modules", "__pycache__", ".git", "dist")]
			probe = dirpath.replace(os.sep, "/") + "/"
			skip = False
			for part in EXCLUDED_PARTS:
				if part in probe:
					skip = True
					break
			if skip:
				continue
			for name in filenames:
				if not wanted or os.path.splitext(name)[1].lower() in wanted:
					found.append(relative(os.path.join(dirpath, name)))
					if len(found) >= limit:
						return found
	return found


def app_repo(app: str) -> str:
	"""``owner/repo`` from the app's git remote, or ""."""
	from one_bpmn.api.production_review import _repo_for_app

	try:
		return _repo_for_app(app) or ""
	except Exception:  # noqa: BLE001
		return ""


# ── child processes ──────────────────────────────────────────────────────────
def _node() -> str:
	found = shutil.which("node")
	if found:
		return found
	for candidate in ("/usr/bin/node", "/usr/local/bin/node"):
		if os.path.isfile(candidate):
			return candidate
	return ""


def run_prettier(path: str, content: str) -> dict:
	"""Format content the way the pre-commit hook will."""
	prettier = os.path.join(spa_root(), "node_modules", ".bin", "prettier")
	if not os.path.isfile(prettier):
		return {"ok": False, "error": "prettier is not installed in spiff/node_modules."}
	try:
		proc = subprocess.run(
			[prettier, "--stdin-filepath", path or "component.vue"],
			cwd=spa_root(), input=content or "", capture_output=True, text=True,
			timeout=NODE_TIMEOUT,
		)
	except Exception as exc:  # noqa: BLE001
		return {"ok": False, "error": str(exc)[:600]}
	if proc.returncode != 0:
		return {"ok": False, "error": (proc.stderr or "prettier failed")[:1200]}
	return {"ok": True, "content": proc.stdout}


_CHECK_CONFIG = """\
import vue from "@vitejs/plugin-vue"
import frappeui from "frappe-ui/vite"
import path from "path"
import { defineConfig } from "vite"

// Generated by one_bpmn.frontend.primitives.run_build — every output path is
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

_COPY_ENTRIES = ("src", "index.html", "tailwind.config.cjs", "postcss.config.cjs",
                 "package.json", "components.d.ts", "auto-imports.d.ts")
_PROBE = "src/__candidate_probe.js"


def run_build(files: dict | None = None) -> dict:
	"""Compile the SPA with ``files`` applied, in a throwaway copy of the tree.

	``files`` maps SPA-relative paths (``src/views/Thing.vue``) to their content.

	TWO THINGS THIS HAS TO GET RIGHT, both learned the hard way:

	1. It must not be able to damage the running application.
	   ``spiff/vite.config.js`` points the frappe-ui buildConfig plugin at the LIVE
	   asset directory with ``emptyOutDir: true``, and the plugin's ``writeBundle``
	   copies the built index.html over ``www/processa/index.html`` — the shell the
	   site serves. A build using that config and failing part-way would leave the
	   SPA empty. So the source is copied to a temp directory, ``node_modules`` is
	   symlinked, and a config is written whose every output path is temporary.

	2. It must actually compile what the agent wrote.
	   Vite only walks the entry graph, so a component nothing imports yet is never
	   seen — a candidate importing a module that does not exist built CLEAN. Every
	   staged file is therefore pulled in through a generated probe entry.

	Returns ``{ok, applied, errors, warnings, duration_s, output}`` and never
	raises: a failing build is a result the agent is expected to read and act on.
	"""
	node = _node()
	if not node:
		return {"ok": False, "errors": ["node was not found on PATH."], "warnings": [],
		        "duration_s": 0, "output": "", "applied": []}

	src_root = spa_root()
	if not os.path.isdir(os.path.join(src_root, "node_modules")):
		return {"ok": False, "errors": ["spiff/node_modules is missing — run yarn install."],
		        "warnings": [], "duration_s": 0, "output": "", "applied": []}

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
				return {"ok": False, "applied": [],
				        "errors": [f"Refusing to place {rel!r} outside the build copy."],
				        "warnings": [], "duration_s": 0, "output": ""}
			os.makedirs(os.path.dirname(safe), exist_ok=True)
			with open(safe, "w", encoding="utf-8") as fh:
				fh.write(content or "")
			applied.append(str(rel))

		inputs = {"index": os.path.join(work, "index.html")}
		probe_imports = []
		for rel in applied:
			if rel.startswith("src/") and os.path.splitext(rel)[1] in (".vue", ".js", ".ts"):
				probe_imports.append(
					"import " + json.dumps("./" + os.path.relpath(rel, "src").replace(os.sep, "/"))
				)
		if probe_imports:
			probe_path = os.path.join(work, _PROBE)
			os.makedirs(os.path.dirname(probe_path), exist_ok=True)
			with open(probe_path, "w", encoding="utf-8") as fh:
				fh.write("// generated by run_build — forces candidate files into the graph\n")
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

		return {"ok": proc.returncode == 0, "applied": applied, "errors": errors[:20],
		        "warnings": warnings[:15], "duration_s": duration, "output": combined[-4000:]}
	except subprocess.TimeoutExpired:
		return {"ok": False, "applied": [],
		        "errors": [f"The build did not finish within {BUILD_TIMEOUT}s."],
		        "warnings": [], "duration_s": BUILD_TIMEOUT, "output": ""}
	except Exception as exc:  # noqa: BLE001
		return {"ok": False, "applied": [], "errors": [str(exc)[:600]], "warnings": [],
		        "duration_s": 0, "output": ""}
	finally:
		shutil.rmtree(tmp, ignore_errors=True)


# ── delivery ─────────────────────────────────────────────────────────────────
def open_pr(*, repo: str, base_branch: str, head_branch: str, files: dict,
            commit_message: str, pr_title: str, pr_body: str,
            allowed_owners=None) -> dict:
	"""Create the branch, commit ``files``, open the pull request. HTTP only.

	Which files may travel, which repository is allowed, and what the body says
	are all decided by the caller — this places the call and reports what happened.
	``allowed_owners`` is passed straight through to github_sync so the caller's
	decision is also enforced at the point of the write, not only before it.
	"""
	from one_bpmn.api.github_sync import branch_exists, open_customization_pr

	token = frappe.get_cached_doc("Processa Settings").get_password("github_token")
	if not token:
		return {"ok": False, "retryable": False,
		        "error": "No GitHub Access Token is configured in Processa Settings."}
	if not repo:
		return {"ok": False, "retryable": False, "error": "No repository was given."}

	# House work branches off staging, but one_bpmn's DEFAULT branch is version-15,
	# so leaving the choice to github_sync would quietly skip staging. A repo with
	# no staging branch falls back to its default.
	base = base_branch or ""
	if base:
		try:
			if not branch_exists(token=token, repo=repo, branch=base):
				base = ""
		except Exception:  # noqa: BLE001
			frappe.log_error(title="Frontend Agent: base branch probe failed",
			                 message=frappe.get_traceback())
			base = ""

	try:
		url = open_customization_pr(
			token=token, repo=repo, base_branch=base or None, head_branch=head_branch,
			files=files, commit_message=commit_message, pr_title=pr_title, pr_body=pr_body,
			allowed_owners=tuple(allowed_owners or ()),
		)
	except Exception as exc:  # noqa: BLE001
		return {"ok": False, "error": str(exc)[:800], "repository": repo}
	return {"ok": True, "pull_request": url, "repository": repo,
	        "branch": head_branch, "base": base or "(repository default)"}
