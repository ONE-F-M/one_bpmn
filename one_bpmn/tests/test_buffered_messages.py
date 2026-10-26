# Copyright (c) 2026, one-fm and contributors
"""A GitHub message that arrives before its wait starts is kept and delivered when the wait does."""

from __future__ import annotations

import json

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.api.compilation import compile_process_model
from SpiffWorkflow.util.task import TaskState

from one_bpmn.one_bpmn import engine

GATE = "wi_buffer_gate"
OPENED = "github:pull_request:opened"
CLOSED = "github:pull_request:closed"
LATER = "wi_buffer_later"
PROCESS_ID = "wi_buffer_process"
MODEL = "WI Buffered Messages"

MAP = f"""<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
                  xmlns:spiffworkflow="http://spiffworkflow.org/bpmn/schema/1.0/core"
                  id="Defs_{PROCESS_ID}" targetNamespace="http://bpmn.io/schema/bpmn">
  <bpmn:message id="Msg_gate" name="{GATE}" />
  <bpmn:message id="Msg_opened" name="{OPENED}" />
  <bpmn:message id="Msg_later" name="{LATER}" />
  <bpmn:process id="{PROCESS_ID}" isExecutable="true">
    <bpmn:startEvent id="s"><bpmn:outgoing>f1</bpmn:outgoing></bpmn:startEvent>
    <bpmn:sequenceFlow id="f1" sourceRef="s" targetRef="gate" />
    <bpmn:intermediateCatchEvent id="gate" name="Gate">
      <bpmn:incoming>f1</bpmn:incoming><bpmn:outgoing>f2</bpmn:outgoing>
      <bpmn:messageEventDefinition messageRef="Msg_gate" />
    </bpmn:intermediateCatchEvent>
    <bpmn:sequenceFlow id="f2" sourceRef="gate" targetRef="opened" />
    <bpmn:intermediateCatchEvent id="opened" name="Opened">
      <bpmn:incoming>f2</bpmn:incoming><bpmn:outgoing>f3</bpmn:outgoing>
      <bpmn:messageEventDefinition messageRef="Msg_opened" />
    </bpmn:intermediateCatchEvent>
    <bpmn:sequenceFlow id="f3" sourceRef="opened" targetRef="later" />
    <bpmn:intermediateCatchEvent id="later" name="Later">
      <bpmn:incoming>f3</bpmn:incoming><bpmn:outgoing>f4</bpmn:outgoing>
      <bpmn:messageEventDefinition messageRef="Msg_later" />
    </bpmn:intermediateCatchEvent>
    <bpmn:sequenceFlow id="f4" sourceRef="later" targetRef="e" />
    <bpmn:endEvent id="e"><bpmn:incoming>f4</bpmn:incoming></bpmn:endEvent>
  </bpmn:process>
</bpmn:definitions>"""


class TestBufferedMessages(FrappeTestCase):
	def setUp(self):
		self._instances: list[str] = []
		if frappe.db.exists("BPMN Process Model", MODEL):
			frappe.delete_doc("BPMN Process Model", MODEL, force=1, ignore_permissions=True)
		model = frappe.new_doc("BPMN Process Model")
		model.name = MODEL
		model.title = MODEL
		model.process_id = PROCESS_ID
		model.bpmn_xml = MAP
		model.version = 1
		model.flags.ignore_permissions = True
		model.insert(ignore_permissions=True)
		compile_process_model(model.name)

	def tearDown(self):
		for name in self._instances:
			if frappe.db.exists("BPMN Process Instance", name):
				frappe.delete_doc("BPMN Process Instance", name, force=True, ignore_permissions=True)
		if frappe.db.exists("BPMN Process Model", MODEL):
			frappe.delete_doc("BPMN Process Model", MODEL, force=True, ignore_permissions=True)
		frappe.db.rollback()
		super().tearDown()

	def _instance(self, docname="WI-BUFFER-1"):
		inst = frappe.new_doc("BPMN Process Instance")
		inst.process_model = MODEL
		inst.context_doctype = "Process Implementation"
		inst.context_docname = docname
		inst.flags.ignore_links = True
		inst.insert(ignore_permissions=True)
		inst.start()
		inst.reload()
		self._instances.append(inst.name)
		return inst

	def _waiting_on(self, inst):
		inst.reload()
		wf = engine.restore_workflow(
			workflow_state=inst._load_json(inst.workflow_state),
			context_doctype=inst.context_doctype,
			context_docname=inst.context_docname,
		)
		return sorted(t.task_spec.bpmn_name for t in wf.get_tasks(state=TaskState.WAITING) if t.task_spec.bpmn_name)

	def _buffered(self, inst):
		inst.reload()
		return json.loads(inst.buffered_messages) if inst.buffered_messages else []

	def test_an_early_message_is_delivered_when_its_wait_starts(self):
		inst = self._instance()

		inst.receive_message(OPENED, {"pr_url": "https://github.com/o/r/pull/1"})
		self.assertEqual([m["name"] for m in self._buffered(inst)], [OPENED])
		self.assertEqual(self._waiting_on(inst), ["Gate"])

		inst.receive_message(GATE)

		self.assertEqual(self._waiting_on(inst), ["Later"])
		self.assertEqual(self._buffered(inst), [])

	def test_a_message_that_arrives_while_the_wait_is_open_still_works(self):
		inst = self._instance()
		inst.receive_message(GATE)
		self.assertEqual(self._waiting_on(inst), ["Opened"])

		inst.reload()
		inst.receive_message(OPENED, {"pr_url": "https://github.com/o/r/pull/2"})

		self.assertEqual(self._waiting_on(inst), ["Later"])
		self.assertEqual(self._buffered(inst), [])

	def test_an_expired_message_is_not_delivered_and_is_cleared(self):
		inst = self._instance()
		inst.receive_message(OPENED, {"pr_url": "https://github.com/o/r/pull/3"})
		old = frappe.utils.add_to_date(frappe.utils.now(), hours=-25)
		inst.db_set("buffered_messages", json.dumps([{**self._buffered(inst)[0], "received_at": old}]))

		inst.reload()
		inst.receive_message(GATE)

		self.assertEqual(self._waiting_on(inst), ["Opened"])
		self.assertEqual(self._buffered(inst), [])

	def test_a_message_outside_the_buffered_names_is_dropped_as_before(self):
		inst = self._instance()
		inst.receive_message(LATER)
		self.assertEqual(self._buffered(inst), [])

	def test_a_buffered_name_the_diagram_never_waits_for_is_dropped(self):
		inst = self._instance()
		inst.receive_message(CLOSED, {"pr_url": "x"})
		self.assertEqual(self._buffered(inst), [])

	def test_an_identical_message_is_kept_once_and_a_different_one_beside_it(self):
		inst = self._instance()
		inst.receive_message(OPENED, {"pr_url": "a"})
		inst.reload()
		inst.receive_message(OPENED, {"pr_url": "a"})
		inst.reload()
		inst.receive_message(OPENED, {"pr_url": "b"})
		self.assertEqual([m["payload"]["pr_url"] for m in self._buffered(inst)], ["a", "b"])

	def test_only_the_newest_messages_are_kept(self):
		inst = self._instance()
		for number in range(inst.BUFFERED_MESSAGES_KEPT + 3):
			inst.reload()
			inst.receive_message(OPENED, {"pr_url": str(number)})
		kept = [m["payload"]["pr_url"] for m in self._buffered(inst)]
		self.assertEqual(len(kept), inst.BUFFERED_MESSAGES_KEPT)
		self.assertEqual(kept[-1], str(inst.BUFFERED_MESSAGES_KEPT + 2))

	def test_a_message_for_one_instance_never_reaches_another(self):
		first = self._instance("WI-BUFFER-A")
		second = self._instance("WI-BUFFER-B")

		first.receive_message(OPENED, {"pr_url": "https://github.com/o/r/pull/9"})
		second.receive_message(GATE)

		self.assertEqual(self._waiting_on(second), ["Opened"])
		self.assertEqual(len(self._buffered(first)), 1)


class TestDeclaresMessage(FrappeTestCase):
	def setUp(self):
		spec, subprocess_specs = engine.parse_bpmn(MAP, PROCESS_ID)
		self.wf = engine.create_workflow(spec, subprocess_specs)

	def test_a_message_a_catch_event_waits_for_is_declared(self):
		self.assertTrue(engine.declares_message(self.wf, OPENED))
		self.assertTrue(engine.declares_message(self.wf, GATE))

	def test_a_message_nothing_waits_for_is_not(self):
		self.assertFalse(engine.declares_message(self.wf, CLOSED))
		self.assertFalse(engine.declares_message(self.wf, ""))
