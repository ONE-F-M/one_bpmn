# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""WI-001933: the poller — backoff, deadlines, waking what waits.

The poller is what makes a long delegation cheap: the process is parked,
and this job checks in on a widening interval until the remote finishes,
asks a question, or runs out of time.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_to_date, get_datetime, now_datetime

from one_bpmn import tasks
from one_bpmn.one_bpmn.integrations import a2a_client
from one_bpmn.tests.test_a2a_client import CARD, wire_task


def make_remote(**kwargs):
	defaults = {
		"doctype": "A2A Remote Agent",
		"agent_name": f"_Test Poll Remote {frappe.generate_hash(length=8)}",
		"endpoint_url": "https://remote.example.com/rpc",
		"enabled": 1,
		"approval_status": "Draft",
		"poll_base_interval": 60,
		"poll_max_interval": 900,
	}
	defaults.update(kwargs)
	remote = frappe.get_doc(defaults).insert(ignore_permissions=True)
	remote.db_set("agent_card", frappe.as_json(CARD), update_modified=False)
	remote.reload()
	remote.approval_status = "Approved"
	remote.save(ignore_permissions=True)
	return remote


def make_outbound(remote, **kwargs):
	defaults = {
		"doctype": "A2A Task",
		"direction": "Outbound",
		"state": "working",
		"remote_agent": remote.name,
		"remote_task_id": "remote-task-1",
		"wf_task_id": "00000000-0000-0000-0000-0000000000aa",
		"next_poll_at": add_to_date(now_datetime(), seconds=-1),
		"deadline": add_to_date(now_datetime(), minutes=60),
		"poll_attempts": 0,
	}
	defaults.update(kwargs)
	task = frappe.get_doc(defaults)
	task.flags.ignore_links = True
	return task.insert(ignore_permissions=True)


def stub_client(**overrides):
	"""Patch the transport-facing client calls the poller makes."""
	patches = {
		"tasks_get": MagicMock(return_value=wire_task()),
		"tasks_cancel": MagicMock(return_value=wire_task(state="canceled")),
	}
	patches.update(overrides)
	return patches


class TestA2APoller(FrappeTestCase):
	"""The poller commits — it has to, so a claim is durable before the
	network call — which means FrappeTestCase's rollback cannot undo the rows
	these tests create. Every fixture is therefore deleted explicitly, or the
	suite would leave registry entries and tasks behind on whatever site it
	runs against (they showed up in the modeler's remote-agent dropdown)."""

	def setUp(self):
		super().setUp()
		self.made: list[tuple[str, str]] = []

	def tearDown(self):
		for doctype, name in reversed(self.made):
			frappe.delete_doc(doctype, name, force=True, ignore_permissions=True, ignore_missing=True)
		frappe.db.commit()
		super().tearDown()

	def remote(self, **kwargs):
		doc = make_remote(**kwargs)
		self.made.append(("A2A Remote Agent", doc.name))
		return doc

	def outbound(self, remote, **kwargs):
		doc = make_outbound(remote, **kwargs)
		self.made.append(("A2A Task", doc.name))
		return doc

	def _run_poller(self, patches, enqueue=None):
		enqueue = enqueue or MagicMock()
		with patch.multiple(a2a_client, **patches), patch(
			"one_bpmn.one_bpmn.doctype.bpmn_process_instance.bpmn_process_instance._enqueue_a2a_resume",
			enqueue,
		):
			tasks.poll_a2a_tasks()
		return enqueue

	def test_completed_remote_stores_result_and_wakes_the_process(self):
		remote = self.remote()
		task = self.outbound(remote)
		enqueue = self._run_poller(
			stub_client(
				tasks_get=MagicMock(return_value=wire_task(state="completed", text="remote answer"))
			)
		)
		task.reload()
		self.assertEqual(task.state, "completed")
		self.assertEqual(frappe.parse_json(task.result)["text"], "remote answer")
		self.assertTrue(task.completed_at)
		enqueue.assert_called_once()

	def test_failed_remote_wakes_the_process_too(self):
		remote = self.remote()
		task = self.outbound(remote)
		enqueue = self._run_poller(
			stub_client(tasks_get=MagicMock(return_value=wire_task(state="failed")))
		)
		task.reload()
		self.assertEqual(task.state, "failed")
		enqueue.assert_called_once()

	def test_still_working_backs_off_and_does_not_wake(self):
		remote = self.remote()
		task = self.outbound(remote)
		before = get_datetime(task.next_poll_at)
		enqueue = self._run_poller(stub_client())
		task.reload()
		self.assertEqual(task.state, "working")
		self.assertEqual(task.poll_attempts, 1)
		self.assertGreater(get_datetime(task.next_poll_at), before)
		self.assertTrue(task.last_polled_at)
		enqueue.assert_not_called()

	def test_backoff_is_capped(self):
		remote = self.remote(poll_base_interval=60, poll_max_interval=120)
		task = self.outbound(remote, poll_attempts=10)
		self._run_poller(stub_client())
		task.reload()
		self.assertLessEqual(
			(get_datetime(task.next_poll_at) - now_datetime()).total_seconds(), 121
		)

	def test_deadline_cancels_remotely_and_times_out(self):
		remote = self.remote()
		task = self.outbound(remote, deadline=add_to_date(now_datetime(), minutes=-1))
		cancel = MagicMock(return_value=wire_task(state="canceled"))
		enqueue = self._run_poller(stub_client(tasks_cancel=cancel))
		task.reload()
		self.assertEqual(task.state, "timed-out")
		self.assertIn("deadline", (task.error_message or "").lower())
		cancel.assert_called_once()
		enqueue.assert_called_once()

	def test_revoked_mid_flight_fails_closed(self):
		remote = self.remote()
		task = self.outbound(remote)
		enqueue = self._run_poller(
			stub_client(
				tasks_get=MagicMock(
					side_effect=a2a_client.A2ANotApprovedError("remote agent was revoked")
				)
			)
		)
		task.reload()
		self.assertEqual(task.state, "failed")
		self.assertIn("revoked", (task.error_message or "").lower())
		enqueue.assert_called_once()

	def test_input_required_asks_a_person_and_stops_polling(self):
		remote = self.remote()
		task = self.outbound(remote, instance="FAKE-INSTANCE")
		asked = MagicMock()
		instance = MagicMock()
		instance._on_a2a_input_required = asked
		with patch.multiple(
			a2a_client,
			**stub_client(
				tasks_get=MagicMock(
					return_value={
						"id": "remote-task-1",
						"kind": "task",
						"status": {
							"state": "input-required",
							"message": {
								"role": "agent",
								"parts": [{"kind": "text", "text": "which repo?"}],
							},
						},
					}
				)
			),
		), patch("frappe.get_doc", side_effect=_get_doc_with(instance, remote)):
			tasks.poll_a2a_tasks()
		task.reload()
		self.assertEqual(task.state, "input-required")
		asked.assert_called_once()
		self.assertIn("which repo", asked.call_args[0][1])

	def test_terminal_tasks_are_not_polled(self):
		remote = self.remote()
		self.outbound(remote, state="completed")
		polled = MagicMock(return_value=wire_task())
		self._run_poller(stub_client(tasks_get=polled))
		polled.assert_not_called()


def _get_doc_with(instance, remote):
	"""frappe.get_doc that hands back a stub instance but real remotes."""
	real = frappe.get_doc

	def fake(*args, **kwargs):
		if args and args[0] == "BPMN Process Instance":
			return instance
		return real(*args, **kwargs)

	return fake
