# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""ProsAlly's AI jobs run on their own queue; every other agent keeps the shared one (WI-003582)."""

import unittest
from unittest import mock

from one_bpmn.agents.job_limits import (
	AI_AGENT_QUEUE,
	AI_AGENT_QUEUES,
	PROSALLY_AGENT_ID,
	PROSALLY_AI_QUEUE,
	ai_agent_queue,
)


class TestAiAgentQueue(unittest.TestCase):
	def test_prosally_goes_on_long(self):
		self.assertEqual(ai_agent_queue(PROSALLY_AGENT_ID), "long")
		self.assertEqual(ai_agent_queue("prosally_agent"), PROSALLY_AI_QUEUE)

	def test_other_agents_keep_the_shared_queue(self):
		for agent_id in ("docu_agent", "logix_agent", "lucrusher_agent", "ba_architect", "", None):
			self.assertEqual(ai_agent_queue(agent_id), "bpmn_ai_agent")
		self.assertEqual(AI_AGENT_QUEUE, "bpmn_ai_agent")

	def test_job_status_checks_both_queues(self):
		self.assertEqual(set(AI_AGENT_QUEUES), {"bpmn_ai_agent", "long"})

	def test_instance_queue_follows_its_agent(self):
		from one_bpmn.one_bpmn.doctype.bpmn_process_instance.bpmn_process_instance import (
			BPMNProcessInstance,
		)

		instance = BPMNProcessInstance.__new__(BPMNProcessInstance)
		instance.process_model = "Some Model"
		path = "one_bpmn.one_bpmn.doctype.bpmn_process_instance.bpmn_process_instance.frappe.db.get_value"
		with mock.patch(path, return_value="prosally_agent"):
			self.assertEqual(instance._ai_job_queue(), "long")
		with mock.patch(path, return_value="docu_agent"):
			self.assertEqual(instance._ai_job_queue(), "bpmn_ai_agent")
		with mock.patch(path, side_effect=Exception("db down")):
			self.assertEqual(instance._ai_job_queue(), "bpmn_ai_agent")
		instance.process_model = None
		self.assertEqual(instance._ai_job_queue(), "bpmn_ai_agent")
