# Copyright (c) 2026, one-fm and contributors
"""LuCrusher memory is keyed by the confirmed business Process.

Run with:
    bench run-tests --app one_bpmn --module one_bpmn.tests.test_lucrusher_memory_by_process
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.agents.executor import ErrorCode, Executor, ExecutorResult, TokenUsage, register_executor
from one_bpmn.agents.memory import tools, writeback
from one_bpmn.one_bpmn.doctype.bpmn_process_instance import dispatchers as D
from one_bpmn.one_bpmn.patches.v1_0 import lucrusher_memory_keyed_by_process as memory_patch

_CAPTURED = {}


class _FakeExecutor(Executor):
	def run(self, config, context):
		_CAPTURED["config"] = config
		return ExecutorResult(output="out", token_usage=TokenUsage(1, 2, 3), error_code=ErrorCode.SUCCESS)


register_executor("faketestprocess", _FakeExecutor)

# Role records stand in for Process records: the keys only need a DocType and a name that exist.
KEY_DOCTYPE = "Role"
ABSENCE = "Guest"
PROMOTION = "Desk User"
OTHER_USER = "Guest"

CFG = {
	"aiBackend": "faketestprocess",
	"aiLongTermMemory": "1",
	"aiMemoryScope": "Entity",
	"aiMemoryWriteMode": "distilled",
	"aiSystemPrompt": "SYS",
	"aiUserPrompt": "rule prefers short long answers",
}


def _instance(context_doctype="Chat Conversation", context_docname="CONV-1"):
	return SimpleNamespace(
		name="INST-X",
		context_doctype=context_doctype,
		context_docname=context_docname,
		process_model="",
		initiated_by="Administrator",
	)


def _task(data):
	return SimpleNamespace(data=data, task_spec=SimpleNamespace(bpmn_id="Act_1", name="Act_1"))


def _entity_row(reference_name, content):
	frappe.get_doc(
		{
			"doctype": "AI Memory",
			"memory_scope": "Entity",
			"reference_doctype": KEY_DOCTYPE,
			"reference_name": reference_name,
			"content": content,
		}
	).insert(ignore_permissions=True)


def _user_row(user, content):
	frappe.get_doc({"doctype": "AI Memory", "memory_scope": "User", "user": user, "content": content}).insert(
		ignore_permissions=True
	)


class TestMemoryTargetFromTaskData(FrappeTestCase):
	def test_task_data_keys_win_over_the_instance_context(self):
		data = {"memory_reference_doctype": "Process", "memory_reference_name": "Absence"}
		target = D._resolve_memory_target({"aiMemoryScope": "Entity"}, _instance(), "Act_1", data)
		self.assertEqual(target, ("Entity", {"reference_doctype": "Process", "reference_name": "Absence"}))

	def test_without_the_keys_the_instance_context_is_used(self):
		target = D._resolve_memory_target({"aiMemoryScope": "Entity"}, _instance(), "Act_1", {})
		self.assertEqual(target, ("Entity", {"reference_doctype": "Chat Conversation", "reference_name": "CONV-1"}))

	def test_blank_keys_mean_no_memory(self):
		data = {"memory_reference_doctype": "", "memory_reference_name": ""}
		self.assertIsNone(D._resolve_memory_target({"aiMemoryScope": "Entity"}, _instance(), "Act_1", data))


class TestUserScope(FrappeTestCase):
	def test_user_scope_needs_a_user(self):
		with self.assertRaises(frappe.ValidationError):
			tools._resolve_scope("User", {})

	def test_user_scope_reads_the_exact_user_only(self):
		keys = tools._resolve_scope("User", {"user": "Administrator"})
		self.assertEqual(tools._read_filters(keys)["user"], "Administrator")

	def test_user_row_without_a_user_is_rejected(self):
		doc = frappe.get_doc({"doctype": "AI Memory", "memory_scope": "User", "content": "x"})
		with self.assertRaises(frappe.ValidationError):
			doc.insert(ignore_permissions=True)


class TestDispatchRecall(FrappeTestCase):
	def setUp(self):
		_CAPTURED.clear()
		for target in (
			"one_bpmn.agents.observability.record_ai_step",
			"one_bpmn.agents.observability.finalize_ai_run",
			"one_bpmn.agents.observability.finalize_ai_run_on_exception",
			"frappe.db.commit",
		):
			p = patch(target)
			p.start()
			self.addCleanup(p.stop)
		p = patch(
			"one_bpmn.agents.observability.create_ai_run",
			return_value=SimpleNamespace(name="RUN-FAKE", stub=False),
		)
		p.start()
		self.addCleanup(p.stop)
		p = patch("one_bpmn.one_bpmn.engine.get_task_display_name", return_value="AI Task")
		p.start()
		self.addCleanup(p.stop)

	def test_recall_is_the_confirmed_process_plus_the_requesters_own_rows(self):
		_entity_row(ABSENCE, "absence rule one")
		_entity_row(PROMOTION, "promotion rule two")
		_user_row("Administrator", "administrator prefers short answers")
		_user_row(OTHER_USER, "guest prefers long answers")
		data = {"memory_reference_doctype": KEY_DOCTYPE, "memory_reference_name": ABSENCE}
		with patch("one_bpmn.agents.memory.writeback.distill_and_write"):
			D.dispatch_ai_agent(_instance("", ""), _task(data), CFG, "Act_1")
		prompt = _CAPTURED["config"].user_prompt
		self.assertIn("absence rule one", prompt)
		self.assertIn("administrator prefers short answers", prompt)
		self.assertNotIn("promotion rule two", prompt)
		self.assertNotIn("guest prefers long answers", prompt)

	def test_unconfirmed_process_reads_and_writes_nothing(self):
		data = {"memory_reference_doctype": "", "memory_reference_name": ""}
		with patch("one_bpmn.agents.memory.tools.memory_search") as search, patch(
			"one_bpmn.agents.memory.writeback.distill_and_write"
		) as distill:
			D.dispatch_ai_agent(_instance(), _task(data), CFG, "Act_1")
		search.assert_not_called()
		distill.assert_not_called()

	def test_distillation_gets_the_requester_and_the_process_key(self):
		data = {"memory_reference_doctype": KEY_DOCTYPE, "memory_reference_name": ABSENCE}
		with patch("one_bpmn.agents.memory.writeback.distill_and_write") as distill:
			D.dispatch_ai_agent(_instance(), _task(data), CFG, "Act_1")
		kwargs = distill.call_args.kwargs
		self.assertEqual(kwargs["scope"], "Entity")
		self.assertEqual(kwargs["scope_key"], {"reference_doctype": KEY_DOCTYPE, "reference_name": ABSENCE})
		self.assertEqual(kwargs["user"], "Administrator")


class TestWritebackRouting(FrappeTestCase):
	FACTS = [
		{"content": "absence needs a manager", "topic": "approval", "dedup_key": "a:approval", "audience": "process"},
		{"content": "keeps answers short", "topic": "style", "dedup_key": "a:style", "audience": "user"},
	]

	def _write(self, user):
		scope_key = {"reference_doctype": "Process", "reference_name": "Absence"}
		with patch.object(writeback, "_distill_with_retries", return_value=[dict(f) for f in self.FACTS]), patch.object(
			writeback, "_reconcile_batch", side_effect=lambda facts, ctx: facts
		), patch("one_bpmn.agents.memory.tools.memory_write", return_value={"name": "M"}) as write:
			writeback.distill_and_write(
				agent_output="x",
				agent="a",
				scope="Entity",
				scope_key=scope_key,
				provider_name="p",
				backend="direct_api",
				model="m",
				source_run=None,
				user=user,
			)
		return [(c.args[0], c.args[1]) for c in write.call_args_list]

	def test_preference_facts_are_written_as_user_rows(self):
		calls = self._write("Administrator")
		self.assertIn(("Entity", {"reference_doctype": "Process", "reference_name": "Absence"}), calls)
		self.assertIn(("User", {"user": "Administrator"}), calls)

	def test_without_a_requester_every_fact_keeps_the_resolved_scope(self):
		calls = self._write(None)
		self.assertEqual({scope for scope, _ in calls}, {"Entity"})


class TestBuildContextKeys(FrappeTestCase):
	def _run(self, confirmed, known=("Absence",)):
		scope = {
			"context_state": {"confirmed_process": confirmed} if confirmed is not None else {},
			"result": {},
			"frappe": SimpleNamespace(db=SimpleNamespace(exists=lambda doctype, name: name in known)),
		}
		exec(memory_patch.KEYS_BLOCK, scope)  # nosemgrep
		return scope["result"]

	def test_confirmed_process_as_a_dict(self):
		result = self._run({"name": "Absence"})
		self.assertEqual(result, {"memory_reference_doctype": "Process", "memory_reference_name": "Absence"})

	def test_confirmed_process_as_a_string(self):
		self.assertEqual(self._run("Absence")["memory_reference_name"], "Absence")

	def test_unknown_process_name_sets_blank_keys(self):
		self.assertEqual(self._run("Made Up"), {"memory_reference_doctype": "", "memory_reference_name": ""})

	def test_no_confirmed_process_sets_blank_keys(self):
		self.assertEqual(self._run(None), {"memory_reference_doctype": "", "memory_reference_name": ""})


class TestMemoryKeysPatch(FrappeTestCase):
	CODE = "x = 1\nset_turn(conversation_id, {\n})\n"

	def test_add_keys_needs_the_anchor_exactly_once(self):
		self.assertIsNone(memory_patch.add_keys("x = 1\n"))
		self.assertIsNone(memory_patch.add_keys(self.CODE + self.CODE))
		self.assertIn(memory_patch.MARKER, memory_patch.add_keys(self.CODE))

	def test_second_run_changes_nothing(self):
		store = {"script": self.CODE}
		writes = []

		def set_value(doctype, name, field, value, **kwargs):
			if doctype == "Server Script":
				store["script"] = value
				writes.append(value)

		with patch.object(frappe.db, "exists", return_value=True), patch.object(
			frappe.db, "get_value", side_effect=lambda *a, **k: store["script"] if a[0] == "Server Script" else None
		), patch.object(frappe.db, "set_value", side_effect=set_value):
			memory_patch.execute()
			memory_patch.execute()
		self.assertEqual(len(writes), 1)

	def test_missing_anchor_is_logged_and_not_written(self):
		with patch.object(frappe.db, "exists", return_value=True), patch.object(
			frappe.db, "get_value", side_effect=lambda *a, **k: "x = 1\n" if a[0] == "Server Script" else None
		), patch.object(frappe.db, "set_value") as set_value, patch.object(frappe, "log_error") as log_error:
			memory_patch.execute()
		set_value.assert_not_called()
		log_error.assert_called_once()
