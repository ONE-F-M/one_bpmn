# Copyright (c) 2026, one-fm and contributors

"""Tests for .github/scripts/check_structure.py, one group per rule, on small in-memory fixtures.

Fixture text that the check would flag (work-item IDs, permission skips, raw SQL, restricted
imports) is built from pieces so that this file passes the check itself.
"""

import importlib.util
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCRIPT = os.path.join(ROOT, ".github", "scripts", "check_structure.py")

_spec = importlib.util.spec_from_file_location("check_structure", SCRIPT)
cs = importlib.util.module_from_spec(_spec)
# dataclasses looks the module up in sys.modules while the class is built
sys.modules["check_structure"] = cs
_spec.loader.exec_module(cs)

WORK_ITEM = "WI" + "-" + "004347"
SKIP_PERMISSIONS = "ignore_permissions" + "=" + "True"
RAW_SQL = "frappe.db." + "sql("
SPIFF_IMPORT = "from " + "SpiffWorkflow.util.task import TaskState"
ANTHROPIC_IMPORT = "import " + "anthropic"
OPENAI_IMPORT = "from " + "openai import AsyncOpenAI"
GENAI_IMPORT = "from " + "google.genai import types"
FETCH = "fet" + "ch("
DEFINITIONS = "one_bpmn/ai_agent_registry/definitions"

CODEOWNERS = "/.github/ @ks093\nAGENTS.md @ks093\n"
BASELINE_FILE = ".github/structure_baseline.txt"


def lines(count):
	return "x = 1\n" * count


def run(changes, baseline=None, base_baseline=None, approvers=(), codeowners=CODEOWNERS):
	return cs.run_checks(changes, baseline or {}, base_baseline, approvers, codeowners)


def rules(result):
	return [finding.rule for finding in result.failures]


class TestSizeRule(unittest.TestCase):
	def test_new_python_file_over_800_lines_fails_and_names_file_and_size(self):
		result = run([cs.Change.new_file("one_bpmn/new_module.py", lines(801))])
		self.assertEqual(rules(result), ["size"])
		message = str(result.failures[0])
		self.assertIn("one_bpmn/new_module.py", message)
		self.assertIn("801 lines", message)

	def test_new_vue_file_over_500_lines_fails_and_names_file_and_size(self):
		result = run([cs.Change.new_file("spiff/src/components/Big.vue", lines(501))])
		self.assertEqual(rules(result), ["size"])
		self.assertIn("spiff/src/components/Big.vue", str(result.failures[0]))
		self.assertIn("501 lines", str(result.failures[0]))

	def test_files_at_the_limit_pass(self):
		result = run(
			[
				cs.Change.new_file("one_bpmn/ok.py", lines(800)),
				cs.Change.new_file("spiff/src/Ok.vue", lines(500)),
			]
		)
		self.assertTrue(result.ok)

	def test_other_file_types_have_no_size_limit(self):
		self.assertTrue(run([cs.Change.new_file("docs/long.md", lines(5000))]).ok)


class TestWorkItemIdRule(unittest.TestCase):
	def added(self, text, path="one_bpmn/mod.py"):
		return run([cs.Change.modified(path, text, [(7, text)])])

	def test_id_in_a_comment_fails_and_names_the_line(self):
		result = self.added(f"x = 1  # fixes {WORK_ITEM}")
		self.assertEqual(rules(result), ["work-item-id"])
		self.assertEqual(result.failures[0].line, 7)
		self.assertIn("one_bpmn/mod.py:7", str(result.failures[0]))

	def test_id_in_a_docstring_fails(self):
		self.assertEqual(rules(self.added(f'"""See {WORK_ITEM} for the history."""')), ["work-item-id"])

	def test_id_in_a_string_fails(self):
		self.assertEqual(rules(self.added(f'label = "{WORK_ITEM}"')), ["work-item-id"])

	def test_id_in_patches_txt_fails(self):
		result = self.added(f"one_bpmn.patches.v1.fix  # {WORK_ITEM}", path="one_bpmn/patches.txt")
		self.assertEqual(rules(result), ["work-item-id"])

	def test_id_in_an_added_file_name_fails(self):
		result = run([cs.Change.new_file(f"one_bpmn/tests/test_{WORK_ITEM}.py", "x = 1\n")])
		self.assertEqual(rules(result), ["work-item-id"])

	def test_lines_without_an_id_pass(self):
		self.assertTrue(self.added("x = 1  # an ordinary comment").ok)

	def test_an_id_that_was_already_there_is_not_flagged(self):
		change = cs.Change.modified("one_bpmn/mod.py", f"# {WORK_ITEM}\ny = 2\n", [(2, "y = 2")])
		self.assertTrue(run([change]).ok)


class TestUnsafeCallRule(unittest.TestCase):
	def added(self, text):
		return run([cs.Change.modified("one_bpmn/api/thing.py", text, [(12, text)])])

	def test_skipped_permissions_without_a_reason_fails_and_names_the_line(self):
		result = self.added(f"\tdoc.insert({SKIP_PERMISSIONS})")
		self.assertEqual(rules(result), ["permissions"])
		self.assertEqual(result.failures[0].line, 12)

	def test_skipped_permissions_with_a_reason_comment_passes(self):
		self.assertTrue(self.added(f"\tdoc.insert({SKIP_PERMISSIONS})  # system job writes the log").ok)

	def test_a_pragma_alone_is_not_a_reason(self):
		self.assertEqual(rules(self.added(f"\tdoc.insert({SKIP_PERMISSIONS})  # noqa")), ["permissions"])

	def test_raw_sql_without_a_reason_fails_and_names_the_line(self):
		result = self.added(f'\trows = {RAW_SQL}"select 1")')
		self.assertEqual(rules(result), ["raw-sql"])
		self.assertEqual(result.failures[0].line, 12)

	def test_raw_sql_with_a_reason_comment_passes(self):
		self.assertTrue(self.added(f'\trows = {RAW_SQL}"select 1")  # no ORM for this aggregate').ok)

	def test_a_comment_only_line_is_not_a_call(self):
		self.assertTrue(self.added(f"\t# never pass {SKIP_PERMISSIONS} here").ok)

	def test_other_sql_helpers_are_not_flagged(self):
		self.assertTrue(self.added('\tnames = frappe.db.sql_list("select name from tabX")').ok)

	def test_only_python_files_are_checked(self):
		change = cs.Change.modified("spiff/src/a.js", "x", [(1, f"// {SKIP_PERMISSIONS}")])
		self.assertTrue(run([change]).ok)


class TestTestLocationRule(unittest.TestCase):
	def added_test(self, path):
		return run([cs.Change.new_file(path, "x = 1\n")])

	def test_test_file_beside_the_code_fails(self):
		result = self.added_test("one_bpmn/agents/test_new_thing.py")
		self.assertEqual(rules(result), ["test-location"])
		self.assertIn("one_bpmn/agents/test_new_thing.py", str(result.failures[0]))

	def test_test_file_directly_in_the_doctype_folder_fails(self):
		self.assertEqual(rules(self.added_test("one_bpmn/one_bpmn/doctype/test_loose.py")), ["test-location"])

	def test_test_file_in_a_doctype_folder_passes(self):
		self.assertTrue(self.added_test("one_bpmn/one_bpmn/doctype/ai_model/test_ai_model.py").ok)

	def test_test_file_in_a_module_tests_folder_passes(self):
		self.assertTrue(self.added_test("one_bpmn/agents/tests/test_new_thing.py").ok)

	def test_test_file_in_one_bpmn_tests_passes(self):
		self.assertTrue(self.added_test("one_bpmn/tests/test_new_thing.py").ok)

	def test_suffix_style_test_file_outside_fails(self):
		self.assertEqual(rules(self.added_test("one_bpmn/utils/thing_test.py")), ["test-location"])

	def test_a_file_that_is_not_a_test_passes(self):
		self.assertTrue(self.added_test("one_bpmn/agents/helpers.py").ok)

	def test_moving_a_baselined_test_file_asks_for_the_entry_to_be_deleted(self):
		old = "one_bpmn/agents/test_old.py"
		result = run(
			[cs.Change.deleted(old), cs.Change.new_file("one_bpmn/tests/test_old.py", "x = 1\n")],
			baseline={("test-location", old): 0},
			base_baseline={("test-location", old): 0},
		)
		self.assertTrue(result.ok)
		self.assertTrue(any("delete" in notice and old in notice for notice in result.notices))


class TestImportRule(unittest.TestCase):
	def added(self, path, text):
		return run([cs.Change.modified(path, text, [(3, text)])])

	def test_spiffworkflow_outside_the_engine_fails_and_names_the_line(self):
		result = self.added("one_bpmn/agents/tool_pool.py", SPIFF_IMPORT)
		self.assertEqual(rules(result), ["import"])
		self.assertEqual(result.failures[0].line, 3)

	def test_spiffworkflow_inside_the_engine_passes(self):
		self.assertTrue(self.added("one_bpmn/processa_engine/engine/__init__.py", SPIFF_IMPORT).ok)
		self.assertTrue(self.added("one_bpmn/processa_engine/engine/parser.py", "\t" + SPIFF_IMPORT).ok)

	def test_spiffworkflow_in_the_old_engine_or_the_instance_folder_fails(self):
		self.assertEqual(rules(self.added("one_bpmn/one_bpmn/engine.py", SPIFF_IMPORT)), ["import"])
		instance = "one_bpmn/processa_engine/doctype/bpmn_process_instance/bpmn_process_instance.py"
		self.assertEqual(rules(self.added(instance, SPIFF_IMPORT)), ["import"])

	def test_model_libraries_outside_the_adapters_fail(self):
		for text in (ANTHROPIC_IMPORT, OPENAI_IMPORT, GENAI_IMPORT, "from google import genai"):
			with self.subTest(text=text):
				self.assertEqual(rules(self.added("one_bpmn/agents/executor/direct_api.py", text)), ["import"])

	def test_model_libraries_inside_the_adapters_pass(self):
		for text in (ANTHROPIC_IMPORT, OPENAI_IMPORT, GENAI_IMPORT):
			with self.subTest(text=text):
				self.assertTrue(self.added("one_bpmn/agents/llm_provider/new_adapter.py", "\t\t" + text).ok)

	def test_tests_may_import_restricted_libraries(self):
		self.assertTrue(self.added("one_bpmn/tests/test_x.py", SPIFF_IMPORT).ok)
		self.assertTrue(self.added("one_bpmn/tests/test_x.py", ANTHROPIC_IMPORT).ok)

	def test_unrelated_imports_pass(self):
		self.assertTrue(self.added("one_bpmn/agents/x.py", "import json").ok)


class TestPrivateImportRule(unittest.TestCase):
	def added(self, path, text, baseline=None):
		return run([cs.Change.modified(path, text, [(1, text)])], baseline)

	def test_absolute_private_import_fails_and_names_the_import(self):
		text = "from one_bpmn.api.compilation import _check_shape_config_drift"
		result = self.added("one_bpmn/api/other.py", text)
		self.assertEqual(rules(result), ["private-import"])
		self.assertIn("one_bpmn.api.compilation._check_shape_config_drift", str(result.failures[0]))

	def test_relative_private_import_fails(self):
		result = self.added("one_bpmn/security/audit.py", "from .pii import _config_name")
		self.assertEqual(rules(result), ["private-import"])
		self.assertIn("one_bpmn.security.pii._config_name", str(result.failures[0]))

	def test_name_on_its_own_line_in_a_bracketed_import_fails(self):
		text = "from one_bpmn.security.pii import (\n\tpublic_name,\n\t_config_name,\n)\n"
		change = cs.Change.modified("one_bpmn/api/x.py", text, [(3, "\t_config_name,")])
		self.assertEqual(rules(run([change])), ["private-import"])

	def test_public_dunder_own_module_and_outside_names_pass(self):
		for path, text in (
			("one_bpmn/api/x.py", "from one_bpmn.security.pii import config_name"),
			("one_bpmn/api/x.py", "from one_bpmn import __version__"),
			("one_bpmn/security/pii.py", "from one_bpmn.security.pii import _config_name"),
			("one_bpmn/api/x.py", "from frappe.utils import _cast"),
		):
			with self.subTest(text=text):
				self.assertTrue(self.added(path, text).ok)

	def test_tests_may_import_private_names(self):
		self.assertTrue(
			self.added("one_bpmn/tests/test_x.py", "from one_bpmn.security.pii import _config_name").ok
		)

	def test_a_baselined_import_passes(self):
		key = ("private-import", "one_bpmn/api/x.py one_bpmn.security.pii._config_name")
		text = "from one_bpmn.security.pii import _config_name"
		self.assertTrue(
			run([cs.Change.modified("one_bpmn/api/x.py", text, [(1, text)])], {key: 0}, {key: 0}).ok
		)

	def test_removing_a_baselined_import_passes_and_asks_for_the_entry_to_be_deleted(self):
		baseline = {("private-import", "one_bpmn/api/x.py one_bpmn.security.pii._config_name"): 0}
		result = run([cs.Change.modified("one_bpmn/api/x.py", "x = 1\n", [(1, "x = 1")])], baseline, baseline)
		self.assertTrue(result.ok)
		self.assertTrue(any("delete" in notice and "_config_name" in notice for notice in result.notices))


class TestDefinitionsRules(unittest.TestCase):
	def added_file(self, path, text="x = 1\n"):
		return run([cs.Change.new_file(f"{DEFINITIONS}/{path}", text)])

	def test_a_file_name_outside_the_list_fails(self):
		for path in ("logix/utils.py", "shared/misc.py"):
			with self.subTest(path=path):
				result = self.added_file(path)
				self.assertEqual(rules(result), ["definitions-file"])
				self.assertIn(path.split("/")[-1], str(result.failures[0]))

	def test_allowed_file_names_pass(self):
		names = (
			"tools.py",
			"helpers.py",
			"validators.py",
			"tools_drafts.py",
			"helpers_dates.py",
			"validators_xml.py",
			"__init__.py",
			"AGENTS.md",
		)
		for name in names:
			with self.subTest(name=name):
				self.assertTrue(self.added_file(f"logix/{name}").ok)
				self.assertTrue(self.added_file(f"shared/{name}").ok)

	def test_a_file_name_that_repeats_the_agent_folder_fails_and_names_the_file(self):
		result = self.added_file("logix/tools_logix.py")
		self.assertEqual(rules(result), ["definitions-name"])
		self.assertIn("tools_logix.py", str(result.failures[0]))

	def test_a_name_that_only_contains_the_folder_name_inside_a_word_passes(self):
		self.assertTrue(self.added_file("ba/helpers_database.py").ok)

	def test_importing_from_another_agent_folder_fails_and_points_to_shared(self):
		for text in (
			"from one_bpmn.ai_agent_registry.definitions.docu.tools import draft",
			"from ..docu.helpers import draft",
			"from one_bpmn.ai_agent_registry.definitions import docu",
		):
			with self.subTest(text=text):
				result = self.added_file("logix/tools.py", text)
				self.assertEqual(rules(result), ["definitions-import"])
				self.assertIn("definitions/shared/", str(result.failures[0]))

	def test_importing_from_shared_or_the_own_folder_passes(self):
		for text in (
			"from one_bpmn.ai_agent_registry.definitions.shared.helpers import draft",
			"from .helpers import draft",
			"from ..shared.tools import draft",
		):
			with self.subTest(text=text):
				self.assertTrue(self.added_file("logix/tools.py", text).ok)


class TestComponentJsRule(unittest.TestCase):
	def test_a_new_js_file_under_components_fails(self):
		for path in ("spiff/src/components/chat/newThing.js", "frontend/src/components/newThing.js"):
			with self.subTest(path=path):
				result = run([cs.Change.new_file(path, "export const a = 1\n")])
				self.assertEqual(rules(result), ["component-js"])
				self.assertIn(path, str(result.failures[0]))

	def test_vue_files_and_js_outside_components_pass(self):
		for path in ("spiff/src/components/chat/NewThing.vue", "spiff/src/utils/newThing.js"):
			with self.subTest(path=path):
				self.assertTrue(run([cs.Change.new_file(path, "x\n")]).ok)

	def test_a_baselined_js_file_passes(self):
		path = "spiff/src/components/chat/index.js"
		baseline = {("component-js", path): 0}
		self.assertTrue(run([cs.Change.new_file(path, "x\n")], baseline, baseline).ok)

	def test_moving_a_baselined_js_file_out_asks_for_the_entry_to_be_deleted(self):
		path = "spiff/src/components/chat/index.js"
		baseline = {("component-js", path): 0}
		result = run([cs.Change.deleted(path)], baseline, baseline)
		self.assertTrue(result.ok)
		self.assertTrue(any("delete" in notice and path in notice for notice in result.notices))


class TestFetchRule(unittest.TestCase):
	def added(self, path, text):
		return run([cs.Change.modified(path, text, [(5, text)])])

	def test_fetch_in_frontend_code_fails_and_names_the_line(self):
		for path, text in (
			("spiff/src/components/chat/AgentChatPanel.vue", f'\tconst res = await {FETCH}"/api/x")'),
			("frontend/src/bpmn/shared/frappeResource.js", f"\treturn window.{FETCH}path)"),
		):
			with self.subTest(path=path):
				result = self.added(path, text)
				self.assertEqual(rules(result), ["fetch"])
				self.assertEqual(result.failures[0].line, 5)

	def test_the_streaming_client_under_utils_may_fetch(self):
		self.assertTrue(
			self.added("spiff/src/utils/aguiClient.js", f"\tresponse = await {FETCH}ENDPOINT)").ok
		)

	def test_the_streaming_client_outside_utils_fails(self):
		result = self.added("spiff/src/components/chat/aguiClient.js", f"\tresponse = await {FETCH}ENDPOINT)")
		self.assertEqual(rules(result), ["fetch"])

	def test_resource_fetch_comments_and_backend_pass(self):
		for path, text in (
			("spiff/src/pages/List.vue", f"\tinstances.{FETCH})"),
			("spiff/src/pages/List.vue", f"\t// never call {FETCH}) here"),
			("one_bpmn/api/x.py", f"\trequests_{FETCH}url)"),
			("one_bpmn/api/x.py", f"\t{FETCH}url)"),
		):
			with self.subTest(text=text):
				self.assertTrue(self.added(path, text).ok)


class TestBaseline(unittest.TestCase):
	PATH = "one_bpmn/agents/eval_runner.py"

	def test_a_baselined_file_may_change_without_getting_worse(self):
		baseline = {("size", self.PATH): 2915}
		same = run([cs.Change.modified(self.PATH, lines(2915), [(10, "x = 1")])], baseline, baseline)
		smaller = run([cs.Change.modified(self.PATH, lines(2900), [(10, "x = 1")])], baseline, baseline)
		self.assertTrue(same.ok)
		self.assertTrue(smaller.ok)

	def test_a_baselined_file_that_grows_fails(self):
		baseline = {("size", self.PATH): 2915}
		result = run([cs.Change.modified(self.PATH, lines(2916), [(2916, "x = 1")])], baseline, baseline)
		self.assertEqual(rules(result), ["size"])
		self.assertIn("2916", str(result.failures[0]))

	def test_a_file_over_the_limit_and_not_in_the_baseline_fails(self):
		result = run([cs.Change.modified(self.PATH, lines(900), [(1, "x = 1")])], {}, {})
		self.assertEqual(rules(result), ["size"])

	def test_new_lines_in_a_baselined_file_are_still_checked(self):
		baseline = {("size", self.PATH): 2915}
		change = cs.Change.modified(self.PATH, lines(2915), [(4, f"x({SKIP_PERMISSIONS})")])
		self.assertEqual(rules(run([change], baseline, baseline)), ["permissions"])

	def test_fixing_a_size_breach_passes_and_asks_to_delete_the_entry(self):
		baseline = {("size", self.PATH): 2915}
		result = run([cs.Change.modified(self.PATH, lines(700), [(1, "x = 1")])], baseline, baseline)
		self.assertTrue(result.ok)
		self.assertEqual(len(result.notices), 1)
		self.assertIn("delete", result.notices[0])
		self.assertIn(self.PATH, result.notices[0])

	def test_deleting_a_baselined_file_passes_and_asks_to_delete_the_entry(self):
		baseline = {("size", self.PATH): 2915}
		result = run([cs.Change.deleted(self.PATH)], baseline, baseline)
		self.assertTrue(result.ok)
		self.assertTrue(any("delete" in notice and self.PATH in notice for notice in result.notices))

	def test_adding_a_baseline_entry_fails_without_a_code_owner(self):
		head = {("size", "one_bpmn/big.py"): 900}
		for approvers in ((), ("someone-else",)):
			with self.subTest(approvers=approvers):
				result = run([], head, {}, approvers)
				self.assertEqual(rules(result), ["baseline"])
				self.assertIn("code owner", str(result.failures[0]))

	def test_adding_a_baseline_entry_passes_with_a_code_owner_approval(self):
		head = {("size", "one_bpmn/big.py"): 900}
		self.assertTrue(run([], head, {}, ["KS093"]).ok)

	def test_raising_an_entry_counts_as_adding_but_lowering_does_not(self):
		key = ("size", self.PATH)
		self.assertEqual(rules(run([], {key: 3000}, {key: 2915})), ["baseline"])
		self.assertTrue(run([], {key: 2800}, {key: 2915}).ok)
		self.assertTrue(run([], {key: 2915}, {key: 2915}).ok)

	def test_removing_an_entry_needs_no_approval(self):
		self.assertTrue(run([], {}, {("size", self.PATH): 2915}).ok)

	def test_owners_come_from_codeowners(self):
		self.assertEqual(cs.owners_for(BASELINE_FILE, CODEOWNERS), ["ks093"])
		self.assertEqual(cs.owners_for("one_bpmn/api/x.py", CODEOWNERS), [])

	def test_baseline_text_round_trips(self):
		entries = {
			("size", "a/b.py"): 801,
			("test-location", "a/test_b.py"): 0,
			("private-import", "one_bpmn/a.py one_bpmn.b._c"): 0,
		}
		self.assertEqual(cs.parse_baseline(cs.format_baseline(entries)), entries)

	def test_the_committed_baseline_parses_and_lists_only_real_rules(self):
		with open(os.path.join(ROOT, BASELINE_FILE)) as handle:
			entries = cs.parse_baseline(handle.read())
		self.assertTrue(entries)
		self.assertLessEqual(
			{rule for rule, _ in entries}, {"size", "test-location", "private-import", "component-js"}
		)

	def test_generate_baseline_lists_oversize_files_and_misplaced_tests(self):
		files = {
			"one_bpmn/a.py": lines(801),
			"one_bpmn/b.py": lines(800),
			"spiff/src/C.vue": lines(501),
			"one_bpmn/agents/test_d.py": "x = 1\n",
			"one_bpmn/tests/test_e.py": "x = 1\n",
			"one_bpmn/f.py": "from one_bpmn.g import _h, public\n",
			"one_bpmn/tests/test_f.py": "from one_bpmn.g import _h\n",
			"spiff/src/components/chat/i.js": "x\n",
		}
		self.assertEqual(
			cs.generate_baseline(files),
			{
				("size", "one_bpmn/a.py"): 801,
				("size", "spiff/src/C.vue"): 501,
				("test-location", "one_bpmn/agents/test_d.py"): 0,
				("private-import", "one_bpmn/f.py one_bpmn.g._h"): 0,
				("component-js", "spiff/src/components/chat/i.js"): 0,
			},
		)


class TestDiffParsing(unittest.TestCase):
	DIFF = "\n".join(
		[
			"diff --git a/one_bpmn/a.py b/one_bpmn/a.py",
			"index 111..222 100644",
			"--- a/one_bpmn/a.py",
			"+++ b/one_bpmn/a.py",
			"@@ -3,0 +4,2 @@ def f():",
			"+first",
			"+second",
			"@@ -9 +12 @@",
			"-old",
			"+third",
			"diff --git a/one_bpmn/new.py b/one_bpmn/new.py",
			"new file mode 100644",
			"--- /dev/null",
			"+++ b/one_bpmn/new.py",
			"@@ -0,0 +1 @@",
			"+only",
			"diff --git a/one_bpmn/gone.py b/one_bpmn/gone.py",
			"deleted file mode 100644",
			"--- a/one_bpmn/gone.py",
			"+++ /dev/null",
			"@@ -1 +0,0 @@",
			"-bye",
		]
	)

	def test_status_and_added_line_numbers_are_read_from_the_diff(self):
		parsed = cs.parse_diff(self.DIFF)
		self.assertEqual(parsed["one_bpmn/a.py"], ("M", [(4, "first"), (5, "second"), (12, "third")]))
		self.assertEqual(parsed["one_bpmn/new.py"], ("A", [(1, "only")]))
		self.assertEqual(parsed["one_bpmn/gone.py"], ("D", []))
