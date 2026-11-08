"""
Guarantees for the Frontend Agent's Server Scripts.

The tests run the Server Scripts through the same split globals/locals exec that
``agents/shape_tools._run_server_script`` uses, so a flat-namespace mistake fails
here and not mid-turn as a NameError. Pinned here:

  * a path outside the apps tree, or anything generated or vendored, is refused,
    including via a symlink
  * Locate UI routes an upstream DocType to the customisation app
  * a build cannot reach the live asset directory or the served page shell

The build cases shell out to Vite and take about half a minute, so they are
skipped unless the SPA's node_modules is present.
"""

import os
import unittest

import frappe

from one_bpmn.processa_engine.agent_runtime.turn_state import clear_turn, set_turn
from one_bpmn.ai_agent_registry.definitions.frontend_agent import tools as fs
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
		abs_path, refusal = fs.resolve("one_bpmn/spiff/src/router.js")
		self.assertEqual(refusal, "")
		self.assertTrue(abs_path.endswith("spiff/src/router.js"))

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
