"""
Guarantees for the Frontend Agent's authoring primitives.

This module is the one place in the bench where an LLM's output decides which
file gets written and what runs against the source tree, so the properties worth
pinning are the ones that stop it doing damage rather than the ones that make it
useful:

  * a path outside the apps tree, a non-front-end file type, or anything
    generated or vendored is refused — including via a symlink, which is the
    obvious way past a prefix test
  * a build check cannot reach the live asset directory or the served page shell,
    because the plugin it would otherwise use empties that directory and
    overwrites that file
  * a candidate file is actually compiled even when nothing imports it yet
  * generated markup carrying eval, v-html or a credential never reaches delivery
  * the house rubric judges the CHANGE, not the file, so editing an old component
    does not drag its pre-existing violations into the diff

The build cases shell out to Vite and take about half a minute each, so they are
marked and skipped unless the SPA's node_modules is present.
"""

import os
import unittest

import frappe

from one_bpmn.one_bpmn.frontend import authoring


def _spa_installed() -> bool:
	return os.path.isdir(os.path.join(authoring.spa_root(), "node_modules"))


class TestPathContainment(unittest.TestCase):
	"""``resolve`` is the boundary. Everything else trusts it."""

	def test_accepts_a_front_end_source_file(self):
		abs_path, refusal = authoring.resolve("one_bpmn/spiff/src/router/index.js")
		self.assertEqual(refusal, "")
		self.assertTrue(abs_path.endswith("spiff/src/router/index.js"))

	def test_refuses_traversal_out_of_the_apps_tree(self):
		_, refusal = authoring.resolve("../../../etc/passwd")
		self.assertIn("outside the apps directory", refusal)

	def test_refuses_an_absolute_path_elsewhere(self):
		_, refusal = authoring.resolve("/etc/hosts")
		self.assertNotEqual(refusal, "")

	def test_refuses_python_and_config(self):
		for path in ("one_bpmn/one_bpmn/hooks.py", "one_bpmn/setup.py"):
			_, refusal = authoring.resolve(path)
			self.assertIn("not a front-end file type", refusal, path)

	def test_refuses_generated_and_vendored(self):
		for path in (
			"one_bpmn/spiff/node_modules/vue/index.js",
			"one_bpmn/one_bpmn/public/processa/assets/index.js",
		):
			_, refusal = authoring.resolve(path)
			self.assertNotEqual(refusal, "", path)

	def test_a_symlink_out_of_the_tree_is_refused(self):
		"""Containment is checked after the link is resolved, not before."""
		link = os.path.join(authoring.apps_root(), "one_bpmn", "spiff", "src", "_escape_probe.js")
		if os.path.lexists(link):
			os.unlink(link)
		os.symlink("/etc/hosts", link)
		try:
			_, refusal = authoring.resolve("one_bpmn/spiff/src/_escape_probe.js")
			self.assertIn("outside the apps directory", refusal)
		finally:
			os.unlink(link)


class TestScreening(unittest.TestCase):
	"""A narrow malice screen — not a quality judgement."""

	def test_flags_the_constructs_that_turn_a_ui_change_into_an_attack(self):
		code = (
			'<template><div v-html="userInput"></div></template>\n'
			'<script setup>\n'
			'eval("1")\n'
			'const api_key = "sk-live-0123456789"\n'
			'el.innerHTML = payload\n'
			'</script>\n'
		)
		findings = " | ".join(authoring.screen_markup(code, "X.vue"))
		for expected in ("eval()", "v-html", "credential", "innerHTML"):
			self.assertIn(expected, findings)

	def test_passes_an_ordinary_component(self):
		code = (
			'<template><Button @click="go">Go</Button></template>\n'
			'<script setup>\nimport { Button } from "frappe-ui"\n'
			'function go() {}\n</script>\n'
		)
		self.assertEqual(authoring.screen_markup(code, "X.vue"), [])

	def test_delivery_refuses_a_screened_file_outright(self):
		out = authoring.propose_frontend_pr(
			files={"one_bpmn/spiff/src/views/X.vue": '<script setup>eval("1")</script>'},
			title="t", summary="s",
		)
		self.assertFalse(out["ok"])
		self.assertIn("Screening refused", out["error"])

	def test_delivery_refuses_a_change_spanning_two_apps(self):
		"""A pull request belongs to one repository."""
		out = authoring.propose_frontend_pr(
			files={
				"one_bpmn/spiff/src/views/X.vue": "<template><div /></template>",
				"one_fm/one_fm/public/js/x.js": "// noop\n",
			},
			title="t", summary="s",
		)
		self.assertFalse(out["ok"])
		self.assertIn("more than one app", out["error"])


class TestRubricJudgesTheChange(unittest.TestCase):
	"""Pre-existing violations must not force unrelated cleanup into a diff."""

	PATH = "one_bpmn/spiff/src/views/InstanceList.vue"

	def _original(self) -> str:
		abs_path, refusal = authoring.resolve(self.PATH)
		if refusal or not os.path.isfile(abs_path):
			self.skipTest(f"{self.PATH} is not present on this bench")
		with open(abs_path, encoding="utf-8") as fh:
			return fh.read()

	def test_an_untouched_file_introduces_nothing(self):
		review = authoring.rubric_review(self.PATH, self._original())
		self.assertEqual(review["introduced"], [])

	def test_a_new_violation_is_attributed_to_the_change(self):
		altered = self._original().replace(
			'class="h-full flex flex-col bg-gray-50"',
			'class="h-full flex flex-col" style="background:#abcdef"',
			1,
		)
		review = authoring.rubric_review(self.PATH, altered)
		self.assertTrue(any("#abcdef" in f for f in review["introduced"]))

	def test_rubric_catches_the_house_rules(self):
		code = (
			"<template>\n"
			'  <div v-for="x in xs" v-if="x">{{ x }}</div>\n'
			"  <select><option>a</option></select>\n"
			"</template>\n"
			"<script>export default {}</script>\n"
		)
		findings = " | ".join(authoring.rubric_check(code, "X.vue"))
		self.assertIn("v-if and v-for", findings)
		self.assertIn("without :key", findings)
		self.assertIn("raw <select>", findings)
		self.assertIn("Options API", findings)


@unittest.skipUnless(_spa_installed(), "spiff/node_modules is not installed")
class TestBuildCheckIsolation(unittest.TestCase):
	"""The build must be unable to damage the running application.

	``spiff/vite.config.js`` points the frappe-ui buildConfig plugin at the live
	asset directory with ``emptyOutDir: true`` and copies the built index.html over
	the served shell. A check that used that config and failed part-way would leave
	the SPA empty.
	"""

	def _live_state(self):
		root = authoring.apps_root()
		shell = os.path.join(root, "one_bpmn", "one_bpmn", "www", "processa", "index.html")
		assets = os.path.join(root, "one_bpmn", "one_bpmn", "public", "processa")
		shell_bytes = None
		if os.path.isfile(shell):
			with open(shell, "rb") as fh:
				shell_bytes = fh.read()
		listing = sorted(os.listdir(assets)) if os.path.isdir(assets) else None
		return shell_bytes, listing

	def test_a_valid_orphan_component_compiles_and_the_live_tree_is_untouched(self):
		before = self._live_state()
		result = authoring.build_check({
			"src/components/__BuildProbeGood.vue": (
				"<template>\n\t<div>{{ label }}</div>\n</template>\n\n"
				'<script setup>\nimport { ref } from "vue"\n'
				'const label = ref("ok")\n</script>\n'
			)
		})
		self.assertTrue(result["ok"], result.get("errors"))
		self.assertEqual(before, self._live_state(), "build_check touched the live SPA")

	def test_a_broken_candidate_fails_even_though_nothing_imports_it(self):
		"""Vite only compiles what the entry graph reaches, so candidates are forced in.

		Without the generated probe entry this exact file built clean.
		"""
		result = authoring.build_check({
			"src/components/__BuildProbeBroken.vue": (
				'<template><div /></template>\n'
				'<script setup>\nimport { X } from "frappe-ui/does-not-exist"\n</script>\n'
			)
		})
		self.assertFalse(result["ok"])
		self.assertTrue(
			any("does-not-exist" in e for e in result["errors"]),
			result["errors"],
		)

	def test_a_candidate_cannot_be_written_outside_the_build_copy(self):
		result = authoring.build_check({"../../escape.vue": "<template><div /></template>"})
		self.assertFalse(result["ok"])
		self.assertIn("outside the build copy", " ".join(result["errors"]))


class TestLocateUi(unittest.TestCase):
	def test_reports_a_missing_doctype_rather_than_inventing_one(self):
		found = authoring.locate_ui("No Such DocType At All")
		self.assertFalse(found["doctype_exists"])
		self.assertIn("No DocType named", found["note"])

	def test_finds_the_spa_route_rules(self):
		found = authoring.locate_ui("/processa/instances")
		self.assertEqual(found["kind"], "route")
		self.assertTrue(
			any(r["to"] == "processa" for r in found["route_rules"]),
			found["route_rules"],
		)


class TestCatalogue(unittest.TestCase):
	def test_lists_components_that_actually_exist(self):
		catalogue = authoring.component_catalogue()
		if not catalogue["frappe_ui"]:
			self.skipTest("frappe-ui is not installed in spiff/node_modules")
		for expected in ("Button", "Dialog", "FormControl"):
			self.assertIn(expected, catalogue["frappe_ui"])
