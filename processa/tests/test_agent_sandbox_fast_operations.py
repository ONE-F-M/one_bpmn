"""The fast Testing Agent actions as agent_sandbox connector operations: a map calls them, nothing parks, an eval gets dry-run text."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from processa.agents_sandbox.sandbox import ops
from processa.patches.v1_0 import add_agent_sandbox_fast_operations as fast_patch

BRIEF = {"target_app": "processa", "git_branch": "staging", "work_item_description": "Test it.", "run_id": "run-1"}
EXTRA = {
	"write_spec": {"file": "a.spec.js", "content": "test();"},
	"browser_snapshot": {"url": "/app", "role": "Sales User"},
	"trigger_job": {"method": "processa.tasks.daily"},
	"seed_docs": {"docs": [{"doctype": "ToDo"}]},
	"seed_context": {"doctypes": ["ToDo"]},
}


class TestFastOperations(IntegrationTestCase):
	def _call(self, action, params=None, response=None, eval_run=False):
		ctx = {"instance": None, "task": SimpleNamespace(data={}), "operation": action, "bpmn_id": "b"}
		answer = response or {"ok": True, "response": {"fine": True}}
		flags = {"eval_origin": {"eval_run": "e1"}} if eval_run else {"eval_origin": None}
		with patch.object(ops, "dispatch_error", return_value=None), patch.object(ops, "sandbox_dispatch", return_value=answer) as send, \
				patch.dict(frappe.flags, flags):
			return ops.dispatch_action({**BRIEF, **EXTRA[action], **(params or {})}, ctx), ctx, send

	def test_the_five_records_exist_and_use_the_shared_handler(self):
		self.assertEqual([o["value"] for o in fast_patch.OPERATIONS], list(EXTRA))
		for op in fast_patch.OPERATIONS:
			self.assertEqual(op["handlerPath"], "processa.agents_sandbox.sandbox.ops.dispatch_action")
			self.assertEqual(op["value"] in ops.FAST_ACTION_ARGS, True)

	def test_each_action_sends_its_own_args_and_the_run_id_and_returns_the_answer_as_the_output(self):
		for action, extra in EXTRA.items():
			result, ctx, send = self._call(action)
			self.assertEqual(result, {"fine": True}, action)
			args = send.call_args.args[4]
			expected = {**extra, **({} if action == "trigger_job" else {"run_id": "run-1"})}
			self.assertEqual(args, expected, action)
			self.assertNotIn(ops.AGENT_SANDBOX_WAITING_KEY, ctx["task"].data)  # nothing parks

	def test_a_list_given_as_json_text_is_parsed_and_a_bad_one_or_a_missing_argument_is_refused_before_any_call(self):
		_r, _c, send = self._call("seed_docs", {"docs": json.dumps([{"doctype": "ToDo"}])})
		self.assertEqual(send.call_args.args[4]["docs"], [{"doctype": "ToDo"}])
		for action, bad in (("seed_docs", {"docs": "not json"}), ("seed_docs", {"docs": []}), ("seed_context", {"doctypes": ""}),
		                    ("write_spec", {"file": ""}), ("browser_snapshot", {"run_id": ""}), ("trigger_job", {"method": " "})):
			with patch.object(ops, "sandbox_dispatch") as send:
				with self.assertRaises(ops.AgentSandboxError):
					with patch.object(ops, "dispatch_error", return_value=None):
						ops.dispatch_action({**BRIEF, **EXTRA[action], **bad}, {"instance": None, "task": SimpleNamespace(data={}), "operation": action})
				send.assert_not_called()

	def test_a_failed_call_raises_and_a_screenshot_is_dropped_from_the_output(self):
		with self.assertRaises(ops.AgentSandboxError) as caught:
			self._call("seed_docs", response={"ok": False, "error": "prepare the site first"})
		self.assertIn("prepare the site first", str(caught.exception))
		result, _c, _s = self._call("browser_snapshot", response={"ok": True, "response": {"snapshot": "- x", "screenshot_base64": "QUJD"}})
		self.assertEqual(result, {"snapshot": "- x", "screenshot_omitted": True})

	def test_an_eval_gets_dry_run_text_and_sends_nothing(self):
		for action in EXTRA:
			result, ctx, send = self._call(action, eval_run=True)
			self.assertIsNone(result)
			send.assert_not_called()
			self.assertIn(f"Eval dry run: {action} was not sent", ctx["task"].data[ops.EVAL_DRY_RUN_KEY])
