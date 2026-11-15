# Copyright (c) 2026, one-fm and contributors
"""The Testing Agent's spec commands on the Processa side: operation records, how a spec run settles and is reported, the fast
tool scripts, and the guards on how they are dispatched."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import frappe
from frappe.tests.utils import FrappeTestCase

from processa.api import agent_callback as callback
from processa.agents_sandbox.sandbox import ops
from processa.patches.v1_0 import add_agent_sandbox_spec_operations as spec_ops
from processa.patches.v1_0 import add_testing_agent_sandbox_tools as tools_patch
from processa.agents_sandbox.tests.test_agent_sandbox_ops import AgentSandboxCase, _scoped_get_cached_doc

OPERATION = "BPMN Connector Operation"
SPEC_ACTIONS = ("run_specs", "run_specs_on_base")


def _name(operation_id):
	return frappe.db.get_value(OPERATION, {"connector": "agent_sandbox", "operation_id": operation_id}, "name")


class TestSpecOperationRecords(FrappeTestCase):
	def setUp(self):
		if not frappe.db.exists("BPMN Connector", "agent_sandbox"):
			self.skipTest("no agent_sandbox connector on this site")
		for operation_id in SPEC_ACTIONS:
			if name := _name(operation_id):
				frappe.delete_doc(OPERATION, name, force=True, ignore_permissions=True)

	def test_both_are_created_as_slow_dispatch_operations_and_a_repeat_changes_nothing(self):
		spec_ops.execute()
		spec_ops.execute()
		for operation_id in SPEC_ACTIONS:
			doc = frappe.get_doc(OPERATION, _name(operation_id))
			self.assertEqual((doc.execution_type, doc.handler_path, doc.enabled), ("Python Handler", spec_ops.HANDLER, 1))
			self.assertEqual([r.field_name for r in doc.fields], ["target_app", "git_branch", "work_item_description", "run_id"])
		self.assertEqual(frappe.db.count(OPERATION, {"connector": "agent_sandbox", "operation_id": ["in", list(SPEC_ACTIONS)]}), 2)


class TestSettlingSpecRuns(FrappeTestCase):
	RESULT = {
		"status": "specs_run", "code": "head", "summary": {"passed": 1, "failed": 1, "flaky": 1},
		"results": [
			{"criterion": "AC1", "viewport": "desktop", "status": "passed", "file": "ac1.spec.js", "failing_assertion": None, "video": "/o/1.webm"},
			{"criterion": "AC2", "viewport": "desktop", "status": "failed", "file": "ac2.spec.js", "failing_assertion": "expected 1, got 2", "video": None},
			{"criterion": "AC3", "viewport": "mobile", "status": "flaky", "file": "ac3.spec.js", "failing_assertion": "timed out", "video": "/o/3.webm"},
		],
	}

	def _run(self, action, state="completed", result=None, error=""):
		return SimpleNamespace(state=state, retry_of=None, error_message=error, request_payload=json.dumps({"action": action}), result=json.dumps(result or self.RESULT))

	def test_a_finished_spec_run_completes_even_when_specs_failed_and_anything_else_fails(self):
		for action in SPEC_ACTIONS:
			self.assertEqual(callback._settled_fields(action, "specs_run", "", {}), {"state": "completed"})
			failed = callback._settled_fields(action, "failed", "", {"error": "prepare the site first"})
			self.assertEqual((failed["state"], failed["error_message"]), ("failed", "prepare the site first"))
		self.assertEqual(callback._settled_fields("run_tests", "tests_passed", "", {}), {"state": "completed"})
		self.assertEqual(callback._settled_fields("prepare_site", "prepared", "", {}), {"state": "completed"})

	def test_the_agent_reads_counts_and_one_line_per_spec_not_the_whole_json(self):
		text = callback._sandbox_run_answer(self._run("run_specs"))
		self.assertIn("run_specs ran on the head code", text)
		self.assertIn('"passed": 1', text)
		self.assertIn("AC2 | desktop | failed | ac2.spec.js | expected 1, got 2", text)
		self.assertIn("video /o/3.webm", text)
		self.assertNotIn('"results"', text)

	def test_a_long_report_is_cut_for_the_agent_and_a_failed_run_names_its_step(self):
		many = {**self.RESULT, "results": [{**self.RESULT["results"][1], "file": f"s{i}.spec.js"} for i in range(400)]}
		text = callback._sandbox_run_answer(self._run("run_specs_on_base", result=many))
		self.assertLessEqual(len(text), 6100)
		self.assertIn("more specs on the run record", text)
		failed = self._run("run_specs", state="failed", result={"step": "not_prepared"}, error="prepare the site first: run prepare_site")
		self.assertIn("failed at step not_prepared", callback._sandbox_run_answer(failed))

	def test_a_failed_spec_run_is_never_retried_from_the_stored_payload(self):
		for action in SPEC_ACTIONS:
			with patch.object(ops.supervisor, "next_step", return_value={"action": "retry"}):
				self.assertFalse(ops.retry_eligible(SimpleNamespace(action=action, failure_class="env")))


class TestSpecToolDispatch(AgentSandboxCase):
	def _dispatch(self, action="write_spec", args=None, job=False):
		settings = SimpleNamespace(agent_sandbox_url="https://sandbox.example.run.app", get_password=lambda *a, **k: "fake-github-token")
		patches = [
			patch.object(frappe, "get_cached_doc", side_effect=_scoped_get_cached_doc(settings)),
			patch.object(ops, "mint_identity_token", return_value="t"),
			patch("requests.post"),
			patch.object(ops, "work_item_id_for", return_value="WI-1"),
			patch.object(ops.sessions, "uses_job", return_value=job),
		]
		with patches[0], patches[1], patches[2] as post, patches[3], patches[4]:
			result = ops.sandbox_dispatch(action, "processa", "staging", "Test it.", args or {"run_id": "r"})
		return result, post

	def test_the_spec_tools_are_refused_outside_a_job_session_and_never_sent_over_http(self):
		for action in sorted(ops.SPEC_TOOL_ACTIONS):
			result, post = self._dispatch(action)
			self.assertFalse(result["ok"])
			self.assertIn("Job session", result["error"])
			post.assert_not_called()
		self.assertEqual(frappe.get_all("Agent Sandbox Run", filters={"action": "write_spec"}, pluck="state")[0], "failed")

	def test_in_a_job_session_a_page_capture_is_waited_for_longer_and_every_other_tool_gets_the_default(self):
		for action, expected in (("browser_snapshot", 90), ("write_spec", None), ("trigger_job", None), ("read_file", None)):
			with patch.object(ops.sessions, "ensure_session", return_value=SimpleNamespace(name="S")), patch.object(ops.sessions, "enqueue") as enqueue, \
					patch.object(ops.sessions, "wait_for", return_value={"ok": True, "found": True}) as wait:
				result, _post = self._dispatch(action, job=True)
			self.assertTrue(result["ok"], action)
			self.assertEqual(wait.call_args.kwargs["timeout"], expected, action)
			self.assertEqual(enqueue.call_args.args[1:3], ("tool", action))


class TestSpecToolScripts(FrappeTestCase):
	def setUp(self):
		for name in tools_patch.SCRIPTS:
			if frappe.db.exists("Server Script", name):
				frappe.delete_doc("Server Script", name, force=True, ignore_permissions=True)

	def _run(self, name, task_data, response=None, file_cls=None):
		result, sent = {}, []

		def dispatch(*args, **kwargs):
			sent.append(args)
			return response or {"ok": True, "response": {"fine": True}}

		fake = MagicMock()
		fake.get_doc.side_effect = file_cls or (lambda d: MagicMock(insert=lambda **k: SimpleNamespace(file_url="/private/files/snap.jpg")))
		namespace = {"task_data": task_data, "result": result, "context_docname": "A2A-1", "context_doctype": "A2A Task", "bpmn_id": "b",
		             "instance": None, "frappe": fake}
		with patch.object(ops, "sandbox_dispatch", side_effect=dispatch):
			exec(compile(tools_patch.SCRIPTS[name], name, "exec"), namespace)
		return result, sent, fake

	BRIEF = {"target_app": "processa", "git_branch": "staging", "work_item_description": "Test it.", "run_id": "run-1"}

	def test_the_three_scripts_are_created_once_and_updated_on_a_repeat(self):
		tools_patch.execute()
		tools_patch.execute()
		for name in tools_patch.SCRIPTS:
			self.assertEqual(frappe.db.count("Server Script", {"name": name}), 1)
			self.assertEqual(frappe.db.get_value("Server Script", name, "script_type"), "API")

	def test_write_spec_sends_the_run_id_from_the_map_and_the_file_and_content_from_the_model(self):
		result, sent, _ = self._run("Sandbox Tool: Write Spec", {**self.BRIEF, "file": "ac1.spec.js", "content": "test();"})
		self.assertEqual(sent[0][0], "write_spec")
		self.assertEqual(sent[0][4], {"run_id": "run-1", "file": "ac1.spec.js", "content": "test();"})
		self.assertEqual(result, {"fine": True})
		for missing in ({"run_id": ""}, {"file": ""}, {"content": " "}):
			result, sent, _ = self._run("Sandbox Tool: Write Spec", {**self.BRIEF, "file": "a.spec.js", "content": "x", **missing})
			self.assertIn("error", result)
			self.assertEqual(sent, [])

	def test_browser_snapshot_saves_the_screenshot_as_a_private_file_and_returns_a_link_not_base64(self):
		response = {"ok": True, "response": {"snapshot": "- heading", "screenshot_base64": "QUJD", "url": "/app", "role": "Sales User"}}
		with patch("frappe.utils.file_manager.save_file", return_value=SimpleNamespace(file_url="/private/files/snap.jpg")) as save:
			result, sent, _ = self._run("Sandbox Tool: Browser Snapshot", {**self.BRIEF, "url": "/app", "role": "Sales User"}, response)
		self.assertEqual(sent[0][4], {"run_id": "run-1", "url": "/app", "role": "Sales User"})
		self.assertNotIn("screenshot_base64", result)
		self.assertEqual((result["snapshot"], result["screenshot_file"]), ("- heading", "/private/files/snap.jpg"))
		args, kwargs = save.call_args
		self.assertEqual((args[0], args[1], args[2], args[3]), ("snapshot-run-1.jpg", "QUJD", "A2A Task", "A2A-1"))
		self.assertEqual((kwargs["decode"], kwargs["is_private"]), (True, 1))
		result, sent, _ = self._run("Sandbox Tool: Browser Snapshot", {**self.BRIEF, "url": "/app"})
		self.assertIn("error", result)

	def test_every_tool_script_passes_the_security_gate_so_it_can_be_linked_to_a_map(self):
		from processa.ai_agent_security.code_checks.script_validator import validate_script

		for name, code in tools_patch.SCRIPTS.items():
			self.assertEqual(validate_script(code)["findings"], [], name)

	def test_a_site_that_ran_the_first_patch_gets_the_corrected_script(self):
		from processa.patches.v1_0 import fix_browser_snapshot_screenshot_save as fix

		tools_patch.execute()
		frappe.db.set_value("Server Script", "Sandbox Tool: Browser Snapshot", "script", "result['old'] = frappe.get_doc({}).insert(ignore_permissions=True)")
		fix.execute()
		script = frappe.db.get_value("Server Script", "Sandbox Tool: Browser Snapshot", "script")
		self.assertIn("save_file", script)
		self.assertNotIn("ignore_permissions", script)

	def test_trigger_job_passes_the_method_and_an_error_answer_comes_back_as_an_error(self):
		result, sent, _ = self._run("Sandbox Tool: Trigger Job", {**self.BRIEF, "method": "processa.tasks.daily"})
		self.assertEqual(sent[0][4], {"method": "processa.tasks.daily"})
		result, _, _ = self._run("Sandbox Tool: Trigger Job", {**self.BRIEF, "method": "x.y"}, {"ok": False, "error": "refused"})
		self.assertEqual(result, {"error": "refused"})
		result, sent, _ = self._run("Sandbox Tool: Trigger Job", {**self.BRIEF, "method": ""})
		self.assertEqual((("error" in result), sent), (True, []))
