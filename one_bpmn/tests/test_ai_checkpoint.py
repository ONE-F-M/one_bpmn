# Copyright (c) 2026, one-fm and contributors
# Durable AI Agent HITL, story 2 — checkpoint persistence + resume entry point.
#
# Covers:
# - a suspension round-trips through the database checkpoint
# - claim_for_resume is exactly-once (double-resume is a no-op)
# - dispatch_ai_agent SUSPENDED branch: checkpoint written, waiting marker on
#   task.data, NO output/error variables, run left open as "Suspended"
# - resume path: human result injected, cumulative tokens, cross-segment tool
#   evidence, waiting marker cleared

from __future__ import annotations

import json
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.agents import checkpoint
from one_bpmn.agents.executor import ErrorCode, ExecutorResult, TokenUsage


def _suspension(**overrides):
	base = {
		"transcript": [
			{"role": "user", "content": "handle the ticket"},
			{
				"role": "assistant",
				"content": "looking up",
				"tool_calls": [{"id": "a1", "name": "lookup", "arguments": {"q": "so"}}],
			},
			{"role": "tool_results", "results": [{"id": "a1", "name": "lookup", "content": "SO-77 found"}]},
			{
				"role": "assistant",
				"content": "need approval",
				"tool_calls": [
					{"id": "a2", "name": "lookup", "arguments": {"q": "x"}},
					{"id": "h1", "name": "approve_refund", "arguments": {"request": "refund 30 KWD?"}},
				],
			},
		],
		"pending_call": {"id": "h1", "name": "approve_refund", "arguments": {"request": "refund 30 KWD?"}},
		"deferred_results": [{"id": "a2", "name": "lookup", "content": "second lookup"}],
		"trace": [{"role": "tool", "content": "", "tool_calls": [], "prompt_tokens": 40, "completion_tokens": 4, "latency_ms": 5}],
		"turns_used": 2,
		"prompt_tokens": 90,
		"completion_tokens": 9,
	}
	base.update(overrides)
	return base


class _CheckpointTestBase(FrappeTestCase):
	def setUp(self):
		self.instance = frappe.get_doc({
			"doctype": "BPMN Process Instance",
			"process_id": f"test-{frappe.generate_hash(length=6)}",
			"status": "Active",
		})
		self.instance.flags.ignore_mandatory = True
		self.instance.insert(ignore_permissions=True, ignore_mandatory=True)
		self.bpmn_id = "Agent_1"


class TestCheckpointPersistence(_CheckpointTestBase):
	def test_round_trip_persist_and_reload(self):
		run = checkpoint.save_checkpoint(
			None,  # no observability run — a minimal one must be created
			self.instance,
			self.bpmn_id,
			_suspension(),
			system_prompt="sys prompt",
			wf_task_id="wf-uuid-1",
			human_row_id="aihuman::abc",
		)
		self.assertEqual(run.status, "Suspended")

		found = checkpoint.get_suspended_run(self.instance.name, self.bpmn_id)
		self.assertEqual(found, run.name)
		by_row = checkpoint.get_suspended_run(self.instance.name, human_row_id="aihuman::abc")
		self.assertEqual(by_row, run.name)

		checkpoint.store_human_result(run.name, {"action": "Approve", "note": "ok"})
		payload = checkpoint.claim_for_resume(run.name)
		self.assertIsNotNone(payload)
		self.assertEqual(payload["system_prompt"], "sys prompt")
		self.assertEqual(payload["wf_task_id"], "wf-uuid-1")
		self.assertEqual(payload["suspension"]["pending_call"]["name"], "approve_refund")
		self.assertEqual(payload["prompt_tokens_so_far"], 90)

		state = checkpoint.build_resume_state(payload)
		self.assertEqual(state["turns_used"], 2)
		self.assertEqual(json.loads(state["human_result"]), {"action": "Approve", "note": "ok"})
		self.assertEqual(len(state["transcript"]), 4)
		self.assertEqual(state["deferred_results"][0]["name"], "lookup")

	def test_claim_is_exactly_once(self):
		run = checkpoint.save_checkpoint(
			None, self.instance, self.bpmn_id, _suspension(),
			system_prompt="s", wf_task_id="t", human_row_id="aihuman::x",
		)
		first = checkpoint.claim_for_resume(run.name)
		second = checkpoint.claim_for_resume(run.name)
		self.assertIsNotNone(first)
		self.assertIsNone(second)
		self.assertEqual(
			frappe.db.get_value("AI Agent Run", run.name, "status"), "Running"
		)

	def test_cumulative_tokens_across_chained_suspensions(self):
		run = checkpoint.save_checkpoint(
			None, self.instance, self.bpmn_id, _suspension(),
			system_prompt="s", wf_task_id="t", human_row_id="r1",
			prior_prompt_tokens=100, prior_completion_tokens=10,
		)
		payload = json.loads(frappe.db.get_value("AI Agent Run", run.name, "checkpoint"))
		self.assertEqual(payload["prompt_tokens_so_far"], 190)
		self.assertEqual(payload["completion_tokens_so_far"], 19)


class TestDispatcherSuspendResume(_CheckpointTestBase):
	"""Drive dispatch_ai_agent with a scripted executor."""

	TOOL_SHAPES = json.dumps([
		{"bpmn_id": "lookup", "description": "Look things up", "serverScript": "X"},
	])

	def setUp(self):
		super().setUp()
		self.task = frappe._dict({
			"data": {},
			"id": "wf-task-uuid",
			"task_spec": frappe._dict({"name": self.bpmn_id, "description": "Agent"}),
		})
		self.task_cfg = {
			"serviceType": "ai_agent",
			"aiProvider": "Does Not Matter",
			"aiSystemPrompt": "sys",
			"aiUserPrompt": "usr",
			"aiToolShapes": self.TOOL_SHAPES,
			"aiOutputVariable": "agent_out",
		}

	def _dispatch(self, result, resume_run=None):
		from one_bpmn.one_bpmn.doctype.bpmn_process_instance import dispatchers

		def fake_run(_self, config, context):
			fake_run.config = config
			return result

		with patch("one_bpmn.agents.executor.direct_api.DirectApiExecutor.run", new=fake_run):
			dispatchers.dispatch_ai_agent(
				self.instance, self.task, self.task_cfg, self.bpmn_id, resume_run=resume_run
			)
		return fake_run

	def test_suspended_result_checkpoints_and_marks_task(self):
		result = ExecutorResult(
			error_code=ErrorCode.SUSPENDED,
			suspension=_suspension(),
			token_usage=TokenUsage(prompt_tokens=90, completion_tokens=9, total_tokens=99),
			trace=_suspension()["trace"],
		)
		self._dispatch(result)

		# waiting marker, but NO outputs and NO error variables
		marker = self.task.data.get("_bpmn_ai_waiting_human")
		self.assertIsNotNone(marker)
		self.assertEqual(marker["tool"], "approve_refund")
		self.assertNotIn("agent_out", self.task.data)
		self.assertNotIn(f"{self.bpmn_id}_error_code", self.task.data)

		run_name = marker["run"]
		self.assertEqual(
			frappe.db.get_value("AI Agent Run", run_name, "status"), "Suspended"
		)
		payload = json.loads(frappe.db.get_value("AI Agent Run", run_name, "checkpoint"))
		self.assertEqual(payload["wf_task_id"], "wf-task-uuid")
		self.assertEqual(payload["system_prompt"], "sys")

	def test_suspension_does_not_stop_on_error(self):
		# aiStopOnError must not fire for a suspension — it is not a failure.
		self.task_cfg["aiStopOnError"] = "true"
		result = ExecutorResult(error_code=ErrorCode.SUSPENDED, suspension=_suspension())
		self._dispatch(result)  # must not raise
		self.assertIn("_bpmn_ai_waiting_human", self.task.data)

	def test_resume_injects_human_result_and_completes(self):
		from one_bpmn.one_bpmn.doctype.bpmn_process_instance import dispatchers

		# 1. Suspend
		self._dispatch(ExecutorResult(error_code=ErrorCode.SUSPENDED, suspension=_suspension()))
		run_name = self.task.data["_bpmn_ai_waiting_human"]["run"]

		# 2. Human answers
		checkpoint.store_human_result(run_name, {"action": "Approve"})

		# 3. Resume → final answer
		final = ExecutorResult(
			output="refund approved and processed",
			token_usage=TokenUsage(prompt_tokens=50, completion_tokens=5, total_tokens=55),
			trace=[{
				"role": "assistant", "content": "refund approved and processed",
				"tool_calls": [], "prompt_tokens": 50, "completion_tokens": 5, "latency_ms": 3,
			}],
		)
		fake = self._dispatch(final, resume_run=run_name)

		# resume_state reached the executor with the injected human result
		state = fake.config.resume_state
		self.assertEqual(json.loads(state["human_result"]), {"action": "Approve"})
		self.assertEqual(state["turns_used"], 2)

		# output written, marker cleared, tokens cumulative (90+50 / 9+5)
		self.assertEqual(self.task.data["agent_out"], "refund approved and processed")
		self.assertNotIn("_bpmn_ai_waiting_human", self.task.data)
		usage = self.task.data[f"{self.bpmn_id}_token_usage"]
		self.assertEqual(usage["prompt_tokens"], 140)
		self.assertEqual(usage["completion_tokens"], 14)

		# cross-segment evidence: earlier lookups + the human's answer
		results = self.task.data[f"{self.bpmn_id}_toolCallResults"]
		tools = [r["tool"] for r in results]
		self.assertIn("lookup", tools)
		self.assertIn("approve_refund", tools)
		human_entry = next(r for r in results if r["tool"] == "approve_refund")
		self.assertEqual(json.loads(human_entry["result"]), {"action": "Approve"})
		self.assertEqual(self.task.data["approve_refund_toolCallResult"], '{"action": "Approve"}')

		# run finalized as Success
		self.assertEqual(
			frappe.db.get_value("AI Agent Run", run_name, "status"), "Success"
		)

	def test_double_resume_is_noop(self):
		self._dispatch(ExecutorResult(error_code=ErrorCode.SUSPENDED, suspension=_suspension()))
		run_name = self.task.data["_bpmn_ai_waiting_human"]["run"]
		checkpoint.store_human_result(run_name, "yes")

		final = ExecutorResult(output="done")
		first = self._dispatch(final, resume_run=run_name)
		self.assertEqual(self.task.data["agent_out"], "done")

		# Second resume: claim fails, executor never invoked, data unchanged
		self.task.data["agent_out"] = "sentinel"
		second = self._dispatch(ExecutorResult(output="MUST NOT APPEAR"), resume_run=run_name)
		self.assertEqual(self.task.data["agent_out"], "sentinel")
		self.assertFalse(hasattr(second, "config"))

	def test_resume_ai_agent_entry_point(self):
		self._dispatch(ExecutorResult(error_code=ErrorCode.SUSPENDED, suspension=_suspension()))
		run_name = self.task.data["_bpmn_ai_waiting_human"]["run"]

		from one_bpmn.one_bpmn.doctype.bpmn_process_instance import dispatchers

		final = ExecutorResult(output="ok")

		def fake_run(_self, config, context):
			return final

		with patch("one_bpmn.agents.executor.direct_api.DirectApiExecutor.run", new=fake_run):
			ran = dispatchers.resume_ai_agent(
				self.instance, self.task, self.task_cfg, self.bpmn_id,
				human_result={"action": "Reject", "reason": "too costly"},
			)
			self.assertTrue(ran)
			# exactly-once: second call finds nothing to resume
			again = dispatchers.resume_ai_agent(
				self.instance, self.task, self.task_cfg, self.bpmn_id, human_result="x"
			)
			self.assertFalse(again)

		self.assertEqual(self.task.data["agent_out"], "ok")
		self.assertEqual(
			frappe.db.get_value("AI Agent Run", run_name, "status"), "Success"
		)


class TestHumanWaitAccounting(_CheckpointTestBase):
	"""WI-001643: time parked on a person is measured, not silently absorbed
	into duration_ms."""

	def test_suspend_stamps_suspended_at(self):
		run = checkpoint.save_checkpoint(
			None, self.instance, self.bpmn_id, _suspension(),
			system_prompt="s", wf_task_id="t", human_row_id="r1",
		)
		self.assertIsNotNone(
			frappe.db.get_value("AI Agent Run", run.name, "suspended_at")
		)

	def test_resume_banks_the_wait_and_clears_the_stamp(self):
		import datetime
		from frappe.utils import now_datetime

		run = checkpoint.save_checkpoint(
			None, self.instance, self.bpmn_id, _suspension(),
			system_prompt="s", wf_task_id="t", human_row_id="r1",
		)
		# Pretend the person took 30 minutes.
		frappe.db.set_value(
			"AI Agent Run", run.name, "suspended_at",
			now_datetime() - datetime.timedelta(minutes=30),
			update_modified=False,
		)
		self.assertIsNotNone(checkpoint.claim_for_resume(run.name))

		waited, stamp = frappe.db.get_value(
			"AI Agent Run", run.name, ["human_wait_ms", "suspended_at"]
		)
		self.assertGreater(waited, 29 * 60 * 1000)
		self.assertLess(waited, 31 * 60 * 1000)
		# Cleared, so a later resume cannot double-count the same wait.
		self.assertFalse(stamp)

	def test_human_wait_accumulates_across_suspensions(self):
		import datetime
		from frappe.utils import now_datetime

		run = None
		for _ in range(2):
			run = checkpoint.save_checkpoint(
				run, self.instance, self.bpmn_id, _suspension(),
				system_prompt="s", wf_task_id="t", human_row_id="r1",
			)
			frappe.db.set_value(
				"AI Agent Run", run.name, "suspended_at",
				now_datetime() - datetime.timedelta(minutes=10),
				update_modified=False,
			)
			run.reload()
			checkpoint.claim_for_resume(run.name)
			run.reload()

		waited = frappe.db.get_value("AI Agent Run", run.name, "human_wait_ms")
		self.assertGreater(waited, 19 * 60 * 1000)

	def test_cumulative_cache_tokens_across_chained_suspensions(self):
		run = checkpoint.save_checkpoint(
			None, self.instance, self.bpmn_id, _suspension(),
			system_prompt="s", wf_task_id="t", human_row_id="r1",
			prior_cache_read_tokens=1000, prior_cache_write_tokens=100,
		)
		payload = json.loads(frappe.db.get_value("AI Agent Run", run.name, "checkpoint"))
		# _suspension() carries no cache figures, so the priors carry through.
		self.assertEqual(payload["cache_read_tokens_so_far"], 1000)
		self.assertEqual(payload["cache_write_tokens_so_far"], 100)
