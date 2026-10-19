# Copyright (c) 2026, one-fm and contributors
"""ProsAlly's AI jobs run on their own queue at every enqueue site; every other agent keeps the shared one."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from frappe.tests.utils import FrappeTestCase

from one_bpmn.agents.job_limits import (
	AI_AGENT_QUEUE,
	AI_AGENT_QUEUES,
	PROSALLY_AGENT_ID,
	PROSALLY_AI_QUEUE,
	ai_agent_queue,
)
from one_bpmn.one_bpmn.doctype.bpmn_process_instance import bpmn_process_instance as controller

MODULE = "one_bpmn.one_bpmn.doctype.bpmn_process_instance.bpmn_process_instance"
AGENTS = {"ProsAlly Map": "prosally_agent", "Docu Map": "docu_agent"}
REGISTERED = {"short": 300, "default": 300, "long": 1500, AI_AGENT_QUEUE: 600, PROSALLY_AI_QUEUE: 1800}


class QueueCase(FrappeTestCase):
	"""A site where both AI queues are registered under workers in the site config."""

	def setUp(self):
		patcher = patch(f"{MODULE}.get_queues_timeout", return_value=REGISTERED)
		patcher.start()
		self.addCleanup(patcher.stop)


def _get_value(model_of_instance):
	"""A stand-in for frappe.db.get_value that knows the instance's process model and the agent linked to a model."""

	def get_value(doctype, name=None, fieldname=None, *args, **kwargs):
		if doctype == "BPMN Process Instance":
			return model_of_instance
		return AGENTS.get(name["process_model"])

	return get_value


class TestQueueForAgent(FrappeTestCase):
	def test_prosally_has_its_own_queue_and_it_is_not_a_general_one(self):
		self.assertEqual(ai_agent_queue(PROSALLY_AGENT_ID), PROSALLY_AI_QUEUE)
		self.assertEqual(PROSALLY_AI_QUEUE, "bpmn_ai_prosally")
		self.assertNotIn(PROSALLY_AI_QUEUE, ("short", "default", "long"))

	def test_other_agents_keep_the_shared_queue(self):
		for agent_id in ("docu_agent", "logix_agent", "lucrusher_agent", "ba_architect", "", None):
			self.assertEqual(ai_agent_queue(agent_id), AI_AGENT_QUEUE)

	def test_job_status_is_read_from_both_queues(self):
		self.assertEqual(set(AI_AGENT_QUEUES), {AI_AGENT_QUEUE, PROSALLY_AI_QUEUE})


class TestQueueForInstance(QueueCase):
	def test_an_instance_of_the_agents_map_goes_to_the_agents_queue(self):
		with patch(f"{MODULE}.frappe.db.get_value", side_effect=_get_value("unused")):
			self.assertEqual(controller.ai_job_queue("ProsAlly Map"), PROSALLY_AI_QUEUE)
			self.assertEqual(controller.ai_job_queue("Docu Map"), AI_AGENT_QUEUE)

	def test_a_map_with_no_agent_or_no_map_uses_the_shared_queue(self):
		with patch(f"{MODULE}.frappe.db.get_value", side_effect=_get_value("unused")):
			self.assertEqual(controller.ai_job_queue("A Map With No Agent"), AI_AGENT_QUEUE)
			self.assertEqual(controller.ai_job_queue(None), AI_AGENT_QUEUE)

	def test_an_instance_is_followed_to_its_map(self):
		with patch(f"{MODULE}.frappe.db.get_value", side_effect=_get_value("ProsAlly Map")):
			self.assertEqual(controller.ai_job_queue_of("INST-1"), PROSALLY_AI_QUEUE)


class TestEveryEnqueueSiteUsesIt(QueueCase):
	def _queue_of_call(self, enqueue):
		return enqueue.call_args.kwargs["queue"]

	def test_parked_jobs(self):
		instance = controller.BPMNProcessInstance.__new__(controller.BPMNProcessInstance)
		instance.name = "INST-1"
		instance.process_model = "ProsAlly Map"
		instance._pending_ai_jobs = [("ai_agent", "task_1")]
		with (
			patch(f"{MODULE}.frappe.db.get_value", side_effect=_get_value("unused")),
			patch(f"{MODULE}.frappe.enqueue") as enqueue,
		):
			instance._enqueue_parked_ai_jobs()
		self.assertEqual(self._queue_of_call(enqueue), PROSALLY_AI_QUEUE)

	def test_a_delegation_resume(self):
		with (
			patch(f"{MODULE}.frappe.db.get_value", side_effect=_get_value("ProsAlly Map")),
			patch(f"{MODULE}.frappe.enqueue") as enqueue,
		):
			controller._enqueue_a2a_resume("INST-1", "task_1", "")
		self.assertEqual(self._queue_of_call(enqueue), PROSALLY_AI_QUEUE)

	def test_a_sandbox_resume(self):
		with (
			patch(f"{MODULE}.frappe.db.get_value", side_effect=_get_value("ProsAlly Map")),
			patch(f"{MODULE}.frappe.enqueue") as enqueue,
		):
			controller._enqueue_agent_sandbox_resume("INST-1", "task_1", "")
		self.assertEqual(self._queue_of_call(enqueue), PROSALLY_AI_QUEUE)

	def test_a_retry_after_a_failed_job_stays_on_the_agents_queue(self):
		failing = MagicMock()
		failing.resume_parked_ai.side_effect = RuntimeError("engine restore failed")
		with (
			patch(f"{MODULE}.frappe.get_doc", return_value=failing),
			patch(f"{MODULE}.frappe.db.get_value", side_effect=_get_value("ProsAlly Map")),
			patch(f"{MODULE}.frappe.db.set_value"),
			patch(f"{MODULE}.frappe.log_error"),
			patch(f"{MODULE}._job_retry_cap", return_value=2),
			patch(f"{MODULE}.frappe.enqueue") as enqueue,
		):
			controller.run_parked_ai_task("INST-1", "ai_agent", "task_1", attempt=0)
		self.assertEqual(self._queue_of_call(enqueue), PROSALLY_AI_QUEUE)
		self.assertEqual(enqueue.call_args.kwargs["attempt"], 1)

	def test_another_agents_retry_stays_on_the_shared_queue(self):
		failing = MagicMock()
		failing.resume_parked_ai.side_effect = RuntimeError("engine restore failed")
		with (
			patch(f"{MODULE}.frappe.get_doc", return_value=failing),
			patch(f"{MODULE}.frappe.db.get_value", side_effect=_get_value("Docu Map")),
			patch(f"{MODULE}.frappe.db.set_value"),
			patch(f"{MODULE}.frappe.log_error"),
			patch(f"{MODULE}._job_retry_cap", return_value=2),
			patch(f"{MODULE}.frappe.enqueue") as enqueue,
		):
			controller.run_parked_ai_task("INST-2", "ai_agent", "task_1", attempt=0)
		self.assertEqual(self._queue_of_call(enqueue), AI_AGENT_QUEUE)


class TestTheOtherEnqueueSitesUseIt(QueueCase):
	def test_the_watchdog_requeues_a_stranded_prosally_job_on_its_queue(self):
		from one_bpmn import tasks

		instance = MagicMock()
		instance.name = "INST-1"
		unit = {"task_id": "task_1", "kind": "ai_agent", "label": "Draw"}
		with (
			patch("one_bpmn.tasks.frappe.db.count", return_value=0),
			patch("one_bpmn.tasks.frappe.db.get_value", side_effect=_get_value("ProsAlly Map")),
			patch("one_bpmn.tasks.frappe.enqueue") as enqueue,
		):
			tasks._requeue_or_error(instance, unit, 30)
		self.assertEqual(enqueue.call_args.kwargs["queue"], PROSALLY_AI_QUEUE)

	def test_the_watchdog_keeps_another_agents_job_on_the_shared_queue(self):
		from one_bpmn import tasks

		instance = MagicMock()
		instance.name = "INST-2"
		unit = {"task_id": "task_1", "kind": "ai_agent", "label": "Draw"}
		with (
			patch("one_bpmn.tasks.frappe.db.count", return_value=0),
			patch("one_bpmn.tasks.frappe.db.get_value", side_effect=_get_value("Docu Map")),
			patch("one_bpmn.tasks.frappe.enqueue") as enqueue,
		):
			tasks._requeue_or_error(instance, unit, 30)
		self.assertEqual(enqueue.call_args.kwargs["queue"], AI_AGENT_QUEUE)

	def test_a_delegated_answer_resumes_a_prosally_instance_on_its_queue(self):
		from one_bpmn import tasks

		row = SimpleNamespace(
			name="A2A-1", caller_agent_run="RUN-1", caller_instance="INST-1", wf_task_id="wf_1"
		)

		def get_value(doctype, name=None, fieldname=None, *args, **kwargs):
			if doctype == "AI Agent Run":
				return "Suspended" if fieldname == "status" else "{}"
			return _get_value("ProsAlly Map")(doctype, name, fieldname)

		with (
			patch("one_bpmn.tasks.frappe.db.get_value", side_effect=get_value),
			patch("one_bpmn.tasks.frappe.get_doc"),
			patch("one_bpmn.tasks._delegation_answer", return_value="done"),
			patch("one_bpmn.agents.checkpoint.store_human_result"),
			patch("one_bpmn.tasks.frappe.enqueue") as enqueue,
		):
			tasks._resume_waiting_agent(row)
		self.assertEqual(enqueue.call_args.kwargs["queue"], PROSALLY_AI_QUEUE)

	def test_a_dev_agent_answer_resumes_a_prosally_instance_on_its_queue(self):
		from one_bpmn.api import agent_callback

		run = SimpleNamespace(
			name="SBX-1", caller_agent_run="RUN-1", caller_instance="INST-1", caller_wf_task_id="wf_1"
		)

		def get_value(doctype, name=None, fieldname=None, *args, **kwargs):
			if doctype == "AI Agent Run":
				return "Suspended" if fieldname == "status" else "{}"
			return _get_value("ProsAlly Map")(doctype, name, fieldname)

		with (
			patch("one_bpmn.api.agent_callback.frappe.db.get_value", side_effect=get_value),
			patch("one_bpmn.api.agent_callback._sandbox_run_answer", return_value="done"),
			patch("one_bpmn.agents.checkpoint.store_human_result"),
			patch("one_bpmn.api.agent_callback.frappe.enqueue") as enqueue,
		):
			agent_callback._resume_waiting_agent(run)
		self.assertEqual(enqueue.call_args.kwargs["queue"], PROSALLY_AI_QUEUE)


class TestJobStatusChecksBothQueues(FrappeTestCase):
	def test_a_job_on_prosallys_queue_counts_as_running(self):
		from one_bpmn.agents import turn_signal

		def get_queue(name):
			jobs = [SimpleNamespace(id="bpmn-ai-INST-1-task_1")] if name == PROSALLY_AI_QUEUE else []
			return SimpleNamespace(jobs=jobs, name=name)

		with (
			patch("frappe.utils.background_jobs.get_queue", side_effect=get_queue),
			patch("frappe.utils.background_jobs.get_running_jobs_in_queue", return_value=[]),
			patch("frappe.utils.background_jobs.create_job_id", side_effect=lambda text: text),
		):
			self.assertTrue(turn_signal.ai_job_running("INST-1"))
			self.assertFalse(turn_signal.ai_job_running("INST-9"))


class TestAnUnregisteredQueueFallsBack(FrappeTestCase):
	def test_a_site_without_the_queue_uses_the_shared_one_instead_of_failing(self):
		without = {k: v for k, v in REGISTERED.items() if k != PROSALLY_AI_QUEUE}
		with (
			patch(f"{MODULE}.get_queues_timeout", return_value=without),
			patch(f"{MODULE}.frappe.db.get_value", side_effect=_get_value("unused")),
		):
			self.assertEqual(controller.ai_job_queue("ProsAlly Map"), AI_AGENT_QUEUE)

	def test_the_queue_chosen_is_one_frappe_accepts_on_this_site(self):
		from frappe.utils.background_jobs import validate_queue

		with patch(f"{MODULE}.frappe.db.get_value", side_effect=_get_value("unused")):
			validate_queue(controller.ai_job_queue("ProsAlly Map"))

	def test_a_registered_queue_is_still_used(self):
		with (
			patch(f"{MODULE}.get_queues_timeout", return_value=REGISTERED),
			patch(f"{MODULE}.frappe.db.get_value", side_effect=_get_value("unused")),
		):
			self.assertEqual(controller.ai_job_queue("ProsAlly Map"), PROSALLY_AI_QUEUE)
