# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""Same-site delegation — the primary A2A case (WI-001933).

Two agents in one bench. Nothing crosses a trust boundary, so the whole
point of these tests is what is NOT required: no registry entry, no
approved client, no service-user key, no HTTP, and no exposure flag on the
target. What IS still required is the delegating agent's allowed-delegates
list and its loop guardrails, because those bound scope, not identity.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_to_date, now_datetime

from one_bpmn import tasks as scheduled_tasks
from one_bpmn.agents._eval_test_factories import make_agent_configuration
from one_bpmn.agents.a2a import guardrails, local
from one_bpmn.one_bpmn.connectors import a2a_client_ops


def stub_turn(text="local reply", conversation=None):
	return patch(
		"one_bpmn.api.agent_invocation.invoke_agent",
		return_value={"response": text, "conversation": conversation},
	)


class LocalDelegationCase(FrappeTestCase):
	def setUp(self):
		super().setUp()
		# The specialist. Exposed over A2A — that flag is what marks an agent
		# as taking part in agent-to-agent work, local or remote.
		self.worker = make_agent_configuration(a2a_exposed=1)
		# The orchestrator needs no list: the tools on its map decide who it
		# calls. Tests that want a refusal tick restrict_delegates themselves.
		self.orchestrator = make_agent_configuration()

	def ctx(self):
		task = SimpleNamespace(
			id="00000000-0000-0000-0000-00000000loc1".replace("loc1", "0c01"),
			data={},
			task_spec=SimpleNamespace(bpmn_id="ServiceTask_Local", name="ServiceTask_Local"),
		)
		instance = SimpleNamespace(name=None, initiated_by="Administrator", process_model=None)
		return {"instance": instance, "task": task}

	def params(self, **kwargs):
		merged = {
			"agent": self.worker.name,
			"instruction": "review this work item",
			"delegating_agent": self.orchestrator.name,
		}
		merged.update(kwargs)
		return merged


class TestLocalDelegation(LocalDelegationCase):
	def test_exposed_agent_receives_local_work_with_no_registry_or_client(self):
		"""The headline requirement: exposure alone is enough on this site —
		no registry entry, no client record, no list to maintain."""
		self.assertTrue(self.worker.a2a_exposed)
		self.assertFalse(self.orchestrator.restrict_delegates)
		self.assertFalse(self.orchestrator.allowed_delegates)
		with stub_turn("done locally"):
			result = a2a_client_ops.delegate_to_local_agent(self.params(), self.ctx())

		self.assertEqual(result["state"], "completed")
		self.assertEqual(result["text"], "done locally")
		row = frappe.get_doc("A2A Task", result["a2a_task"])
		self.assertEqual(row.direction, "Internal")
		self.assertEqual(row.agent_configuration, self.worker.name)
		self.assertEqual(row.delegated_by, self.orchestrator.name)
		self.assertIsNone(row.remote_agent)
		self.assertIsNone(row.client)

	def test_nothing_is_registered_or_approved(self):
		remotes_before = frappe.db.count("A2A Remote Agent")
		clients_before = frappe.db.count("A2A Client")
		with stub_turn():
			a2a_client_ops.delegate_to_local_agent(self.params(), self.ctx())
		self.assertEqual(
			frappe.db.count("A2A Remote Agent"), remotes_before, "no registry entry should be created"
		)
		self.assertEqual(
			frappe.db.count("A2A Client"), clients_before, "no client record should be created"
		)

	def test_no_http_call_is_made(self):
		from one_bpmn.one_bpmn.integrations import a2a_client

		session = MagicMock()
		with stub_turn(), patch.object(a2a_client, "_session", return_value=session):
			a2a_client_ops.delegate_to_local_agent(self.params(), self.ctx())
		session.post.assert_not_called()
		session.get.assert_not_called()

	def test_target_can_be_named_by_agent_id(self):
		with stub_turn():
			result = a2a_client_ops.delegate_to_local_agent(
				self.params(agent=self.worker.agent_id), self.ctx()
			)
		self.assertEqual(result["state"], "completed")

	def test_counters_start_a_fresh_chain(self):
		with stub_turn():
			result = a2a_client_ops.delegate_to_local_agent(self.params(), self.ctx())
		row = frappe.get_doc("A2A Task", result["a2a_task"])
		self.assertEqual(row.delegation_depth, 1)
		self.assertEqual(row.handoff_count, 1)
		self.assertTrue(row.task_execution_id)

	def test_chain_continues_through_a_parent_task(self):
		with stub_turn():
			first = a2a_client_ops.delegate_to_local_agent(self.params(), self.ctx())
			second = a2a_client_ops.delegate_to_local_agent(
				self.params(parent_task=first["a2a_task"]), self.ctx()
			)
		parent = frappe.get_doc("A2A Task", first["a2a_task"])
		child = frappe.get_doc("A2A Task", second["a2a_task"])
		self.assertEqual(child.task_execution_id, parent.task_execution_id)
		self.assertEqual(child.delegation_depth, 2)

	def test_failed_turn_comes_back_as_a_failed_task(self):
		with patch(
			"one_bpmn.api.agent_invocation.invoke_agent", side_effect=RuntimeError("boom")
		):
			result = a2a_client_ops.delegate_to_local_agent(self.params(), self.ctx())
		self.assertEqual(result["state"], "failed")


class TestLocalDelegationGuards(LocalDelegationCase):
	def test_unexposed_agent_cannot_receive_work(self):
		unexposed = make_agent_configuration()
		with self.assertRaises(guardrails.DelegationRefused) as caught:
			a2a_client_ops.delegate_to_local_agent(self.params(agent=unexposed.name), self.ctx())
		self.assertEqual(caught.exception.reason_code, "target_not_exposed")

	def test_agent_off_the_list_is_refused_when_restricted(self):
		stranger = make_agent_configuration(a2a_exposed=1)
		self.orchestrator.restrict_delegates = 1
		self.orchestrator.append("allowed_delegates", {"agent_configuration": self.worker.name})
		self.orchestrator.save(ignore_permissions=True)

		with self.assertRaises(guardrails.DelegationRefused) as caught:
			a2a_client_ops.delegate_to_local_agent(self.params(agent=stranger.name), self.ctx())
		self.assertEqual(caught.exception.reason_code, "target_not_allowed")
		self.assertFalse(
			frappe.db.exists("A2A Task", {"agent_configuration": stranger.name}),
			"a refused delegation leaves no task row",
		)

	def test_depth_limit_applies_locally_too(self):
		self.orchestrator.max_recursion_depth = 1
		self.orchestrator.save(ignore_permissions=True)
		with stub_turn():
			first = a2a_client_ops.delegate_to_local_agent(self.params(), self.ctx())
		with self.assertRaises(guardrails.DelegationRefused) as caught:
			a2a_client_ops.delegate_to_local_agent(
				self.params(parent_task=first["a2a_task"]), self.ctx()
			)
		self.assertEqual(caught.exception.reason_code, "max_recursion_depth")

	def test_a_draft_agent_cannot_receive_work(self):
		draft = make_agent_configuration(lifecycle_status="Draft", a2a_exposed=1)
		with self.assertRaises(guardrails.DelegationRefused) as caught:
			a2a_client_ops.delegate_to_local_agent(self.params(agent=draft.name), self.ctx())
		self.assertEqual(caught.exception.reason_code, "target_not_live")

	def test_unknown_agent_is_refused(self):
		with self.assertRaises(guardrails.DelegationRefused) as caught:
			a2a_client_ops.delegate_to_local_agent(self.params(agent="no_such_agent"), self.ctx())
		self.assertEqual(caught.exception.reason_code, "unknown_agent")

	def test_dropdown_lists_live_agents_without_needing_exposure(self):
		choices = local.local_agent_choices()
		self.assertIn(self.worker.name, choices)
		self.assertTrue(
			all(
				frappe.db.get_value("AI Agent Configuration", c, "lifecycle_status") == "Live"
				for c in choices
			)
		)


class TestLocalDelegationParking(LocalDelegationCase):
	"""A slow local agent parks the step, and the reconciler wakes it — with
	no network call anywhere in the loop.

	The reconciler commits (a claim must be durable), so rollback cannot undo
	what these tests create and each one clears up after itself — otherwise
	stray rows get reconciled again on the next test's poller run.
	"""

	def tearDown(self):
		for name in frappe.get_all(
			"A2A Task", filters={"direction": "Internal", "bpmn_id": "ServiceTask_Local"}, pluck="name"
		):
			frappe.delete_doc("A2A Task", name, force=True, ignore_permissions=True, ignore_missing=True)
		frappe.db.commit()
		super().tearDown()

	def _park(self):
		# A turn that leaves the task non-terminal: the agent's map suspended
		# for a person, so the row sits at input-required.
		with stub_turn(), patch(
			"one_bpmn.agents.a2a.execute.run_for_task",
			side_effect=lambda task, config, text: task.db_set(
				{"state": "working"}, update_modified=True
			),
		):
			ctx = self.ctx()
			result = a2a_client_ops.delegate_to_local_agent(self.params(), ctx)
		return result, ctx

	def test_slow_agent_parks_the_step(self):
		result, ctx = self._park()
		self.assertIsNone(result, "a working agent should park, not answer")
		marker = ctx["task"].data[a2a_client_ops.A2A_WAITING_KEY]
		row = frappe.get_doc("A2A Task", marker["a2a_task"])
		self.assertEqual(row.state, "working")
		self.assertIsNone(marker["remote_agent"], "nothing remote is involved")

	def test_reconciler_wakes_the_step_without_any_network_call(self):
		from one_bpmn.one_bpmn.integrations import a2a_client

		_result, ctx = self._park()
		marker = ctx["task"].data[a2a_client_ops.A2A_WAITING_KEY]
		row = frappe.get_doc("A2A Task", marker["a2a_task"])
		row.db_set(
			{"next_poll_at": add_to_date(now_datetime(), seconds=-1)}, update_modified=False
		)

		# The agent finishes out of band.
		from one_bpmn.agents.a2a.task_store import store_result

		store_result(row, "finished on its own")

		woken = MagicMock()
		session = MagicMock()
		with patch(
			"one_bpmn.one_bpmn.doctype.bpmn_process_instance.bpmn_process_instance._enqueue_a2a_resume",
			woken,
		), patch.object(a2a_client, "_session", return_value=session):
			scheduled_tasks.poll_a2a_tasks()

		row.reload()
		self.assertEqual(row.state, "completed")
		self.assertIn(
			row.name,
			[call.args[2] for call in woken.call_args_list],
			"the parked step for THIS delegation should have been woken",
		)
		self.assertTrue(row.resume_enqueued)
		session.post.assert_not_called()

	def test_deadline_times_out_a_local_delegation(self):
		_result, ctx = self._park()
		marker = ctx["task"].data[a2a_client_ops.A2A_WAITING_KEY]
		row = frappe.get_doc("A2A Task", marker["a2a_task"])
		row.db_set(
			{
				"deadline": add_to_date(now_datetime(), minutes=-1),
				"next_poll_at": add_to_date(now_datetime(), seconds=-1),
			},
			update_modified=False,
		)
		woken = MagicMock()
		with patch(
			"one_bpmn.one_bpmn.doctype.bpmn_process_instance.bpmn_process_instance._enqueue_a2a_resume",
			woken,
		):
			scheduled_tasks.poll_a2a_tasks()
		row.reload()
		self.assertEqual(row.state, "timed-out")
		self.assertIn(row.name, [call.args[2] for call in woken.call_args_list])
		self.assertTrue(row.resume_enqueued)
