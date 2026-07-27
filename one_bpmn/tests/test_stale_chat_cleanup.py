# Copyright (c) 2026, one-fm and contributors
# Scheduled cleanup for abandoned chat conversations.
#
# Chat process maps park at an event-based gateway waiting for the next user
# message or ChatConversation_Close_Action. The close message normally comes
# from the UI when the chat panel closes — but a killed tab or a lost
# fire-and-forget request orphans the instance as Active forever.
# close_stale_chat_instances() is the hourly backstop that closes them.

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_to_date, now_datetime

from one_bpmn.tasks import STALE_CHAT_HOURS, close_stale_chat_instances

# Minimal chat-shaped map: start → catch ChatConversation_Close_Action → end.
# Mirrors the close branch of the real chat maps — the instance parks WAITING
# at the catch event and only completes when the close message is delivered.
CLOSE_CATCH_MODEL_XML = """<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
    id="defs_stale_chat_test" targetNamespace="http://bpmn.io/schema/bpmn">
  <bpmn:message id="msg_close" name="ChatConversation_Close_Action" />
  <bpmn:process id="stale_chat_test" isExecutable="true">
    <bpmn:startEvent id="start">
      <bpmn:outgoing>flow_start_catch</bpmn:outgoing>
    </bpmn:startEvent>
    <bpmn:sequenceFlow id="flow_start_catch" sourceRef="start" targetRef="catch_close" />
    <bpmn:intermediateCatchEvent id="catch_close" name="Conversation Closed">
      <bpmn:incoming>flow_start_catch</bpmn:incoming>
      <bpmn:outgoing>flow_catch_end</bpmn:outgoing>
      <bpmn:messageEventDefinition messageRef="msg_close" />
    </bpmn:intermediateCatchEvent>
    <bpmn:sequenceFlow id="flow_catch_end" sourceRef="catch_close" targetRef="end_close" />
    <bpmn:endEvent id="end_close">
      <bpmn:incoming>flow_catch_end</bpmn:incoming>
    </bpmn:endEvent>
  </bpmn:process>
</bpmn:definitions>
"""


class TestStaleChatCleanup(FrappeTestCase):
	def _start_chat_instance(self):
		from one_bpmn.api.compilation import compile_process_model

		suffix = frappe.generate_hash(length=6)

		process = frappe.get_doc({
			"doctype": "Process",
			"process_name": f"stale-chat-test-{suffix}",
			"description": "Stale chat cleanup test",
			"process_owner": "Administrator",
		})
		process.insert(ignore_permissions=True)

		model = frappe.get_doc({
			"doctype": "BPMN Process Model",
			"title": f"stale-chat-test-model-{suffix}",
			"process_id": f"stale-chat-test-{suffix}",
			"version": 1,
			"process_name": process.name,
			"bpmn_xml": CLOSE_CATCH_MODEL_XML,
		})
		model.flags.skip_editability_check = True
		model.insert(ignore_permissions=True)
		compile_process_model(model.name)

		conversation = frappe.get_doc({
			"doctype": "Chat Conversation",
			"agent_mode": "AI Assistant",
			"title": f"Stale chat test {suffix}",
			"status": "Open",
		})
		conversation.insert(ignore_permissions=True)

		instance = frappe.get_doc({
			"doctype": "BPMN Process Instance",
			"process_model": model.name,
			"context_doctype": "Chat Conversation",
			"context_docname": conversation.name,
		})
		instance.insert(ignore_permissions=True)
		instance.start(initial_data={})

		self.assertEqual(instance.status, "Active")
		return instance

	def _backdate(self, instance_name: str, hours: int):
		frappe.db.set_value(
			"BPMN Process Instance",
			instance_name,
			"modified",
			add_to_date(now_datetime(), hours=-hours),
			update_modified=False,
		)

	def test_stale_instance_is_closed(self):
		instance = self._start_chat_instance()
		self._backdate(instance.name, STALE_CHAT_HOURS + 1)

		close_stale_chat_instances()

		self.assertEqual(
			frappe.db.get_value("BPMN Process Instance", instance.name, "status"),
			"Completed",
		)

	def test_fresh_instance_is_untouched(self):
		instance = self._start_chat_instance()

		close_stale_chat_instances()

		self.assertEqual(
			frappe.db.get_value("BPMN Process Instance", instance.name, "status"),
			"Active",
		)

	def test_stale_instance_waiting_on_ai_is_skipped(self):
		instance = self._start_chat_instance()
		frappe.db.set_value(
			"BPMN Process Instance", instance.name, "waiting_for_ai", 1,
			update_modified=False,
		)
		self._backdate(instance.name, STALE_CHAT_HOURS + 1)

		close_stale_chat_instances()

		self.assertEqual(
			frappe.db.get_value("BPMN Process Instance", instance.name, "status"),
			"Active",
		)
