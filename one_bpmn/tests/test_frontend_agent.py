"""
Guarantees for the Frontend Agent.

The agent's rules live in its Server Scripts, not in Python, so the tests run the
Server Scripts — through the same SPLIT globals/locals exec that
``agents/shape_tools._run_server_script`` uses. That is deliberate twice over: it
tests the code that actually runs, and it fails on the flat-namespace mistake
(a ``def`` or a comprehension reading a top-level name) that would otherwise only
show up mid-turn as a NameError.

What is pinned here is the behaviour that stops the agent doing damage, plus the
two corrections that came out of watching it work:

  * a path outside the apps tree, a non-authorable file type, or anything
    generated or vendored is refused — including via a symlink
  * an app that is not ours can be neither staged nor delivered into; an upstream
    DocType routes to the customisation app instead
  * generated markup carrying eval, v-html or a credential never gets staged
  * BOTH the malice screen and the house rules judge what the change INTRODUCES,
    so editing an old file does not drag its history into the diff
  * a hooks.py registration is spliced, never regenerated, and never accepts
    Python from the agent
  * a build cannot reach the live asset directory or the served page shell, and
    it compiles candidate files even when nothing imports them yet

The build cases shell out to Vite and take about half a minute, so they are
skipped unless the SPA's node_modules is present.
"""

import ast
import os
import unittest

import frappe

from one_bpmn.agents.turn_state import clear_turn, get_turn, set_turn
from one_bpmn.one_bpmn.frontend import primitives as fs

TURN = "_test_frontend_agent"


def _spa_installed() -> bool:
	return os.path.isdir(os.path.join(fs.spa_root(), "node_modules"))


def run_tool(tool: str, **task_data) -> dict:
	"""Execute a tool's Server Script the way a shape tool would.

	Mirrors ``shape_tools._run_server_script``: LLM arguments are visible both as
	``task_data`` and as bare locals, and globals hold only ``frappe`` and the
	builtins — so anything the script defines at top level is a LOCAL and is
	invisible inside a function body.
	"""
	script = frappe.db.get_value("Server Script", f"Frontend Agent: Tool {tool}", "script")
	if not script:
		raise AssertionError(f"Server Script 'Frontend Agent: Tool {tool}' is not installed")
	result: dict = {}
	local_vars = dict(task_data)
	local_vars.update({
		"frappe": frappe,
		"result": result,
		"task_data": dict(task_data),
		"context_doctype": "A2A Task",
		"context_docname": TURN,
		"doc": frappe._dict(),
		"instance": None,
		"bpmn_id": "",
		"shape_config": {},
		"ai_agent_config": "",
	})
	exec(script, {"frappe": frappe, "__builtins__": __builtins__}, local_vars)  # noqa: S102
	return result


class FrontendAgentCase(unittest.TestCase):
	def setUp(self):
		set_turn(TURN, {"work_order": "test", "a2a_task": TURN, "staged": {}, "findings": {}})

	def tearDown(self):
		clear_turn(TURN)


# ── the primitive that is a security boundary ────────────────────────────────
class TestPathContainment(unittest.TestCase):
	"""``resolve`` stays in Python because it needs realpath, and it is atomic."""

	def test_accepts_a_front_end_source_file(self):
		abs_path, refusal = fs.resolve("one_bpmn/spiff/src/router/index.js")
		self.assertEqual(refusal, "")
		self.assertTrue(abs_path.endswith("spiff/src/router/index.js"))

	def test_refuses_traversal_out_of_the_apps_tree(self):
		_, refusal = fs.resolve("../../../etc/passwd")
		self.assertIn("outside the apps directory", refusal)

	def test_refuses_an_absolute_path_elsewhere(self):
		self.assertNotEqual(fs.resolve("/etc/hosts")[1], "")

	def test_refuses_generated_and_vendored(self):
		for path in ("one_bpmn/spiff/node_modules/vue/index.js",
		             "one_bpmn/one_bpmn/public/processa/assets/index.js"):
			self.assertNotEqual(fs.resolve(path)[1], "", path)

	def test_a_symlink_out_of_the_tree_is_refused(self):
		"""Containment is checked after the link is resolved, not before."""
		link = os.path.join(fs.apps_root(), "one_bpmn", "spiff", "src", "_escape_probe.js")
		if os.path.lexists(link):
			os.unlink(link)
		os.symlink("/etc/hosts", link)
		try:
			_, refusal = fs.resolve("one_bpmn/spiff/src/_escape_probe.js")
			self.assertIn("outside the apps directory", refusal)
		finally:
			os.unlink(link)


# ── reading ──────────────────────────────────────────────────────────────────
class TestReadAndSearch(FrontendAgentCase):
	def test_read_file_returns_a_line_range(self):
		out = run_tool("Read File", path="one_bpmn/spiff/src/router/index.js", start=1, end=5)
		self.assertTrue(out.get("ok"), out.get("error"))
		self.assertEqual(out["first_line"], 1)
		self.assertEqual(len(out["content"].splitlines()), 5)
		self.assertGreater(out["total_lines"], 5)

	def test_read_file_refuses_a_path_it_may_not_see(self):
		self.assertIn("outside", run_tool("Read File", path="../../etc/passwd")["error"])

	def test_read_file_reports_a_start_past_the_end(self):
		out = run_tool("Read File", path="one_bpmn/spiff/src/router/index.js", start=99999)
		self.assertIn("past the end", out["error"])

	def test_search_finds_a_known_symbol(self):
		out = run_tool("Search Frontend", pattern="frappeRequest", apps=["one_bpmn"])
		self.assertTrue(out.get("ok"), out.get("error"))
		self.assertGreater(out["hit_count"], 0)
		self.assertTrue(all(h["path"].startswith("one_bpmn/") for h in out["hits"]))

	def test_search_needs_a_real_needle(self):
		self.assertIn("3 characters", run_tool("Search Frontend", pattern="ab")["error"])

	def test_catalogue_lists_components_that_exist(self):
		out = run_tool("Component Catalogue")
		if not out.get("frappe_ui"):
			self.skipTest("frappe-ui is not installed in spiff/node_modules")
		for expected in ("Button", "Dialog", "FormControl"):
			self.assertIn(expected, out["frappe_ui"])

	def test_doctype_fields_reads_the_live_schema(self):
		out = run_tool("DocType Fields", doctype="ToDo", search="status")
		self.assertEqual(out.get("doctype"), "ToDo")
		self.assertTrue(any(f["fieldname"] == "status" for f in out["fields"]), out["fields"])

	def test_doctype_fields_refuses_an_unknown_doctype(self):
		self.assertIn("No DocType named", run_tool("DocType Fields", doctype="Nope At All")["error"])


# ── which app a change belongs in ────────────────────────────────────────────
class TestAppRouting(FrontendAgentCase):
	def test_locate_ui_routes_an_upstream_doctype_to_the_customisation_app(self):
		out = run_tool("Locate UI", target="Employee")
		if not out.get("doctype_exists"):
			self.skipTest("Employee is not installed")
		self.assertEqual(out["owning_app"], "erpnext")
		route = out["where_to_change"]
		self.assertEqual(route["route"], "customisation")
		self.assertEqual(route["app"], "one_fm")
		self.assertEqual(route["file"], "one_fm/one_fm/public/js/doctype_js/employee.js")
		self.assertEqual(route["hook"]["key"], "Employee")

	def test_locate_ui_leaves_our_own_doctype_in_place(self):
		out = run_tool("Locate UI", target="BPMN Process Model")
		self.assertEqual(out["where_to_change"]["route"], "in_place")
		self.assertEqual(out["owning_app"], "one_bpmn")

	def test_locate_ui_reports_a_missing_doctype_rather_than_inventing_one(self):
		out = run_tool("Locate UI", target="No Such DocType At All")
		self.assertFalse(out["doctype_exists"])
		self.assertIn("No DocType named", out["note"])

	def test_locate_ui_finds_the_spa_route_rules(self):
		out = run_tool("Locate UI", target="/processa/instances")
		self.assertEqual(out["kind"], "route")
		self.assertTrue(any(r["to"] == "processa" for r in out["route_rules"]))

	def test_draft_refuses_to_stage_into_an_upstream_app(self):
		out = run_tool("Draft Change",
		               path="erpnext/erpnext/public/js/probe.js", content="// x\n")
		self.assertIn("Refusing to stage", out["error"])
		self.assertEqual(out["where_to_change"]["app"], "one_fm")

	def test_delivery_refuses_an_upstream_repository(self):
		set_turn(TURN, {"staged": {"erpnext/erpnext/public/js/probe.js": "// x\n"}, "findings": {}})
		out = run_tool("Propose Pull Request", title="t", summary="s")
		self.assertIn("Refusing to open a pull request", out["error"])
		self.assertFalse(out.get("retryable", True))

	def test_delivery_refuses_a_change_spanning_two_apps(self):
		set_turn(TURN, {"staged": {"one_bpmn/spiff/src/views/X.vue": "<template><div /></template>",
		                           "one_fm/one_fm/public/js/x.js": "// noop\n"}, "findings": {}})
		out = run_tool("Propose Pull Request", title="t", summary="s")
		self.assertIn("more than one app", out["error"])

	def test_delivery_refuses_a_failed_build(self):
		set_turn(TURN, {"staged": {"one_bpmn/spiff/src/views/X.vue": "x"},
		                "findings": {}, "build": {"ok": False, "errors": ["boom"]}})
		out = run_tool("Propose Pull Request", title="t", summary="s")
		self.assertIn("build FAILED", out["error"])


# ── what may be authored ─────────────────────────────────────────────────────
class TestDraftGuards(FrontendAgentCase):
	VUE = "one_bpmn/spiff/src/components/__TestProbe.vue"

	def test_refuses_a_file_type_it_may_not_author(self):
		out = run_tool("Draft Change", path="one_bpmn/one_bpmn/hooks.py", content="x = 1\n")
		self.assertIn("Refusing", out["error"])

	def test_refuses_a_fragment(self):
		self.assertIn("content is required", run_tool("Draft Change", path=self.VUE, content=" ")["error"])

	def test_refuses_leaked_tool_call_markup_rather_than_trimming_it(self):
		out = run_tool("Draft Change", path=self.VUE,
		               content='<template><div /></template>\n</content><parameter name="x">y')
		self.assertIn("tool-call markup", out["error"])
		self.assertEqual(get_turn(TURN).get("staged"), {})


class TestScreening(FrontendAgentCase):
	VUE = "one_bpmn/spiff/src/components/__TestProbe.vue"

	def test_blocks_the_constructs_that_turn_a_ui_change_into_an_attack(self):
		out = run_tool("Draft Change", path=self.VUE, content=(
			'<template><div v-html="userInput"></div></template>\n'
			'<script setup>\neval("1")\nconst api_key = "sk-live-0123456789"\n'
			'el.innerHTML = payload\n</script>\n'
		))
		self.assertTrue(out.get("rejected"))
		joined = " | ".join(out["findings"])
		for expected in ("eval()", "v-html", "credential", "innerHTML"):
			self.assertIn(expected, joined)
		self.assertEqual(get_turn(TURN).get("staged"), {}, "a rejected file must not be staged")

	def test_stages_an_ordinary_component(self):
		out = run_tool("Draft Change", path=self.VUE, content=(
			'<template>\n\t<Button @click="go">Go</Button>\n</template>\n\n'
			'<script setup>\nimport { Button } from "frappe-ui"\n'
			'function go() {}\n</script>\n'
		))
		self.assertNotIn("error", out)
		self.assertFalse(out.get("rejected"))
		self.assertEqual(out["rubric"], [])
		self.assertIn(self.VUE, get_turn(TURN)["staged"])


class TestJudgesTheChangeNotTheFile(FrontendAgentCase):
	"""Pre-existing problems must not force unrelated cleanup into a diff."""

	PATH = "one_fm/one_fm/public/js/doctype_js/vehicle.js"

	def _original(self) -> str:
		read = fs.read_text(self.PATH)
		if not read.get("ok"):
			self.skipTest(f"{self.PATH} is not present on this bench")
		return read["content"]

	def test_an_untouched_file_introduces_nothing_and_still_stages(self):
		out = run_tool("Draft Change", path=self.PATH, content=self._original())
		self.assertFalse(out.get("rejected"), out.get("findings"))
		self.assertEqual(out["rubric"], [])
		self.assertTrue(out["pre_existing"], "this fixture should carry known findings")

	def test_a_newly_added_construct_is_still_blocked(self):
		out = run_tool("Draft Change", path=self.PATH,
		               content=self._original() + '\neval("nope")\n')
		self.assertTrue(out.get("rejected"))
		self.assertTrue(any("eval()" in f for f in out["findings"]))

	def test_a_newly_added_house_rule_break_is_attributed_to_the_change(self):
		vue = "one_bpmn/spiff/src/views/InstanceList.vue"
		read = fs.read_text(vue)
		if not read.get("ok"):
			self.skipTest(f"{vue} is not present")
		altered = read["content"].replace(
			'class="h-full flex flex-col bg-gray-50"',
			'class="h-full flex flex-col" style="background:#abcdef"', 1,
		)
		out = run_tool("Draft Change", path=vue, content=altered)
		self.assertTrue(any("#abcdef" in f for f in out["rubric"]), out["rubric"])
		self.assertTrue(out["pre_existing"], "the file's own findings should be reported apart")


# ── wiring a desk script up ──────────────────────────────────────────────────
class TestRegisterHook(FrontendAgentCase):
	def test_adds_a_registration_and_the_file_still_parses(self):
		out = run_tool("Register Hook", app="one_fm", hook="doctype_js",
		               key="ZZ Probe DocType", file="public/js/doctype_js/zz_probe.js")
		self.assertNotIn("error", out)
		self.assertTrue(out["changed"])
		spliced = get_turn(TURN)["staged"]["one_fm/one_fm/hooks.py"]
		self.assertIn('"ZZ Probe DocType": "public/js/doctype_js/zz_probe.js"', spliced)
		ast.parse(spliced)

	def test_is_idempotent(self):
		first = run_tool("Register Hook", app="one_fm", hook="doctype_js",
		                 key="ZZ Probe DocType", file="public/js/doctype_js/zz_probe.js")
		self.assertTrue(first["changed"])
		staged_once = get_turn(TURN)["staged"]["one_fm/one_fm/hooks.py"]
		second = run_tool("Register Hook", app="one_fm", hook="doctype_js",
		                  key="ZZ Probe DocType", file="public/js/doctype_js/zz_probe.js")
		self.assertFalse(second["changed"])
		self.assertEqual(get_turn(TURN)["staged"]["one_fm/one_fm/hooks.py"], staged_once)

	def test_recognises_a_registration_already_in_the_file(self):
		out = run_tool("Register Hook", app="one_fm", hook="doctype_js",
		               key="Employee", file="public/js/doctype_js/employee.js")
		self.assertFalse(out["changed"])
		self.assertEqual(out["note"], "already registered")
		self.assertNotIn("one_fm/one_fm/hooks.py", get_turn(TURN).get("staged") or {})

	def test_appends_after_an_entry_that_has_no_trailing_comma(self):
		"""one_fm's doctype_js leaves its last entry bare — the classic break."""
		out = run_tool("Register Hook", app="one_fm", hook="doctype_js",
		               key="ZZ Comma Probe", file="public/js/doctype_js/zz_comma.js")
		spliced = get_turn(TURN)["staged"]["one_fm/one_fm/hooks.py"]
		ast.parse(spliced)
		self.assertIn('"HR Settings": "public/js/doctype_js/hr_settings.js",', spliced)
		_ = out

	def test_refuses_a_hook_it_may_not_register(self):
		out = run_tool("Register Hook", app="one_fm", hook="doc_events",
		               key="ToDo", file="public/js/x.js")
		self.assertIn("not a hook this may register", out["error"])

	def test_refuses_a_file_path_outside_public_js(self):
		for bad in ("../../../etc/passwd", "one_fm/hooks.py", "/etc/hosts"):
			out = run_tool("Register Hook", app="one_fm", hook="doctype_js", key="ToDo", file=bad)
			self.assertIn("error", out, bad)

	def test_refuses_an_upstream_app(self):
		out = run_tool("Register Hook", app="erpnext", hook="doctype_js",
		               key="Employee", file="public/js/doctype_js/employee.js")
		self.assertIn("not to us", out["error"])


# ── review ───────────────────────────────────────────────────────────────────
class TestReview(FrontendAgentCase):
	def test_nothing_staged_is_reported_not_approved(self):
		self.assertIn("Nothing is staged", run_tool("Review Change")["error"])

	def test_an_unregistered_desk_script_blocks_approval(self):
		set_turn(TURN, {"staged": {"one_fm/one_fm/public/js/doctype_js/zz.js": "// x\n"},
		                "findings": {}})
		out = run_tool("Review Change")
		self.assertFalse(out["approved"])
		self.assertEqual(out["unregistered"], ["one_fm/one_fm/public/js/doctype_js/zz.js"])

	def test_a_registered_desk_script_approves_without_a_build(self):
		set_turn(TURN, {
			"staged": {"one_fm/one_fm/public/js/doctype_js/zz.js": "// x\n"},
			"findings": {}, "registered_files": ["one_fm/one_fm/public/js/doctype_js/zz.js"],
		})
		out = run_tool("Review Change")
		self.assertTrue(out["approved"], out)
		self.assertIsNone(out["build_ok"])
		self.assertIn("nothing for Vite", out["build_note"])

	def test_stored_rubric_findings_block_approval(self):
		path = "one_bpmn/spiff/src/views/X.vue"
		set_turn(TURN, {"staged": {}, "findings": {path: {"rubric": ["X.vue:1 - raw <button>."]}}})
		set_turn(TURN, {"staged": {"one_fm/one_fm/public/js/doctype_js/zz.js": "// x\n"},
		                "registered_files": ["one_fm/one_fm/public/js/doctype_js/zz.js"],
		                "findings": {"one_fm/one_fm/public/js/doctype_js/zz.js":
		                             {"rubric": ["zz.js:1 - raw <button>."]}}})
		out = run_tool("Review Change")
		self.assertFalse(out["approved"])
		self.assertEqual(out["rubric"], ["zz.js:1 - raw <button>."])


# ── the build must not be able to hurt the running app ───────────────────────
@unittest.skipUnless(_spa_installed(), "spiff/node_modules is not installed")
class TestBuildIsolation(unittest.TestCase):
	"""``spiff/vite.config.js`` empties the live asset directory and overwrites the
	served shell, so the check must never use it."""

	def _live_state(self):
		root = fs.apps_root()
		shell = os.path.join(root, "one_bpmn", "one_bpmn", "www", "processa", "index.html")
		assets = os.path.join(root, "one_bpmn", "one_bpmn", "public", "processa")
		shell_bytes = None
		if os.path.isfile(shell):
			with open(shell, "rb") as fh:
				shell_bytes = fh.read()
		return shell_bytes, (sorted(os.listdir(assets)) if os.path.isdir(assets) else None)

	def test_a_valid_orphan_component_compiles_and_the_live_tree_is_untouched(self):
		before = self._live_state()
		out = fs.run_build({
			"src/components/__BuildProbeGood.vue": (
				"<template>\n\t<div>{{ label }}</div>\n</template>\n\n"
				'<script setup>\nimport { ref } from "vue"\nconst label = ref("ok")\n</script>\n'
			)
		})
		self.assertTrue(out["ok"], out.get("errors"))
		self.assertEqual(before, self._live_state(), "the build touched the live SPA")

	def test_a_broken_candidate_fails_even_though_nothing_imports_it(self):
		"""Vite walks only the entry graph, so candidates are forced in."""
		out = fs.run_build({
			"src/components/__BuildProbeBroken.vue": (
				'<template><div /></template>\n'
				'<script setup>\nimport { X } from "frappe-ui/does-not-exist"\n</script>\n'
			)
		})
		self.assertFalse(out["ok"])
		self.assertTrue(any("does-not-exist" in e for e in out["errors"]), out["errors"])

	def test_a_candidate_cannot_be_written_outside_the_build_copy(self):
		out = fs.run_build({"../../escape.vue": "<template><div /></template>"})
		self.assertFalse(out["ok"])
		self.assertIn("outside the build copy", " ".join(out["errors"]))


# ── the answer ───────────────────────────────────────────────────────────────
class TestFinalize(FrontendAgentCase):
	def test_salvages_the_delimiter_leak_the_model_produces(self):
		run_tool("Finalize", summary=(
			"Did the thing.</summary>\n"
			'<parameter name="outstanding">Did not check it in a browser.'
		))
		out = get_turn(TURN)["output"]
		self.assertEqual(out["summary"], "Did the thing.")
		self.assertIn("Did not check it in a browser.", out["outstanding"])
		self.assertNotIn("<parameter", out["summary"])

	def test_reports_a_pull_request_as_the_next_step(self):
		set_turn(TURN, {"staged": {}, "findings": {},
		                "pull_request": "https://github.com/x/y/pull/1", "delivered": ["a.vue"]})
		run_tool("Finalize", summary="Done.")
		out = get_turn(TURN)["output"]
		self.assertEqual(out["lane"], "pull request")
		self.assertIn("merge", out["next_step"])
