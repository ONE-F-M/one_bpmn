# Copyright (c) 2026, one-fm and contributors
# Deploying a process model must tell the engine, so the Process Implementation
# that commissioned the model can conclude on its own.
#
# The awkward part is WHY this needs its own call at all. Every other BPMN
# message reaches an instance through trigger.on_doc_event, but "BPMN Process
# Model" is in trigger._INTERNAL_DOCTYPES — document events on it never reach
# the universal trigger, because that exclusion is what stops the engine
# recursing while it saves its own models. So a deployment has no way to
# announce itself except to say so directly, which is what compile_process_model
# now does.
#
# The delivery is deliberately best-effort: an implementation map only grows a
# catch event when its designer wants to react to a deployment, so "nobody was
# listening" is the normal case and must never fail a deploy.

from __future__ import annotations

import json

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.api.compilation import compile_process_model
from one_bpmn.one_bpmn.trigger import (
	PROCESS_MODEL_DEPLOYED_MESSAGE,
	send_process_model_deployed_message,
)

IMPL_A = "WI2090-IMP-0001"
IMPL_B = "WI2090-IMP-0002"


def _waiting_xml(process_id: str, message_name: str = PROCESS_MODEL_DEPLOYED_MESSAGE) -> str:
	"""An implementation-shaped map that parks on a message catch event."""
	return f"""<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
                  xmlns:spiffworkflow="http://spiffworkflow.org/bpmn/schema/1.0/core"
                  id="Defs_{process_id}" targetNamespace="http://bpmn.io/schema/bpmn">
  <bpmn:message id="Msg_{process_id}" name="{message_name}" />
  <bpmn:process id="{process_id}" isExecutable="true">
    <bpmn:startEvent id="s"><bpmn:outgoing>f1</bpmn:outgoing></bpmn:startEvent>
    <bpmn:sequenceFlow id="f1" sourceRef="s" targetRef="wait" />
    <bpmn:intermediateCatchEvent id="wait" name="Model deployed">
      <bpmn:incoming>f1</bpmn:incoming>
      <bpmn:outgoing>f2</bpmn:outgoing>
      <bpmn:messageEventDefinition messageRef="Msg_{process_id}" />
    </bpmn:intermediateCatchEvent>
    <bpmn:sequenceFlow id="f2" sourceRef="wait" targetRef="e" />
    <bpmn:endEvent id="e"><bpmn:incoming>f2</bpmn:incoming></bpmn:endEvent>
  </bpmn:process>
</bpmn:definitions>"""


def _trivial_xml(process_id: str) -> str:
	"""A deployable map with nothing in it — stands in for the model a process
	owner is deploying."""
	return f"""<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
                  xmlns:spiffworkflow="http://spiffworkflow.org/bpmn/schema/1.0/core"
                  id="Defs_{process_id}" targetNamespace="http://bpmn.io/schema/bpmn">
  <bpmn:process id="{process_id}" isExecutable="true">
    <bpmn:startEvent id="s"><bpmn:outgoing>f1</bpmn:outgoing></bpmn:startEvent>
    <bpmn:sequenceFlow id="f1" sourceRef="s" targetRef="e" />
    <bpmn:endEvent id="e"><bpmn:incoming>f1</bpmn:incoming></bpmn:endEvent>
  </bpmn:process>
</bpmn:definitions>"""


class TestProcessModelDeployedMessage(FrappeTestCase):
	def setUp(self):
		self._models: list[str] = []
		self._instances: list[str] = []

	def tearDown(self):
		for name in self._instances:
			if frappe.db.exists("BPMN Process Instance", name):
				frappe.delete_doc(
					"BPMN Process Instance", name, force=True, ignore_permissions=True
				)
		for name in self._models:
			if frappe.db.exists("BPMN Process Model", name):
				frappe.delete_doc("BPMN Process Model", name, force=True, ignore_permissions=True)

	# ── helpers ──────────────────────────────────────────────────────────
	def _model(self, name, process_id, xml, implementation=None):
		if frappe.db.exists("BPMN Process Model", name):
			frappe.delete_doc("BPMN Process Model", name, force=1, ignore_permissions=True)
		doc = frappe.new_doc("BPMN Process Model")
		doc.name = name
		doc.title = name
		doc.process_id = process_id
		doc.bpmn_xml = xml
		doc.version = 1
		if implementation:
			doc.process_implementation = implementation
		doc.flags.ignore_permissions = True
		doc.insert(ignore_permissions=True)
		self._models.append(name)
		return doc

	def _waiting_instance(self, implementation, message_name=PROCESS_MODEL_DEPLOYED_MESSAGE):
		"""A running implementation instance parked on its catch event."""
		pid = f"wi2090_wait_{abs(hash((implementation, message_name))) % 10000}"
		model = self._model(
			f"WI2090 Waiting {implementation} {message_name[:12]}",
			pid,
			_waiting_xml(pid, message_name),
		)
		compile_process_model(model.name)

		inst = frappe.new_doc("BPMN Process Instance")
		inst.process_model = model.name
		inst.context_doctype = "Process Implementation"
		inst.context_docname = implementation
		# The Process Implementation record itself is irrelevant here — what is
		# under test is the routing by context, so the link is not resolved.
		inst.flags.ignore_links = True
		inst.insert(ignore_permissions=True)
		inst.start()
		inst.reload()
		self._instances.append(inst.name)
		self.assertEqual(inst.status, "Active", "the fixture instance should be parked and waiting")
		return inst

	# ── the contract ─────────────────────────────────────────────────────
	def test_message_name_follows_the_house_convention(self):
		"""{DocType}{Action}_Action, as ChatConversation_Message_Action and
		AIAgentConfiguration_Edit_Action already do — a designer writing the
		catch event should not have to learn a second scheme."""
		self.assertEqual(PROCESS_MODEL_DEPLOYED_MESSAGE, "BPMNProcessModel_Deployed_Action")

	def test_a_model_with_no_implementation_tells_nobody(self):
		"""The story's Given: only a model with a process implementation set."""
		model = self._model("WI2090 No Impl", "wi2090_no_impl", _trivial_xml("wi2090_no_impl"))
		self.assertEqual(send_process_model_deployed_message(model), [])

	def test_an_implementation_with_no_running_instance_is_not_an_error(self):
		model = self._model(
			"WI2090 Orphan Impl",
			"wi2090_orphan",
			_trivial_xml("wi2090_orphan"),
			implementation="WI2090-IMP-NOPE",
		)
		self.assertEqual(send_process_model_deployed_message(model), [])

	def test_the_waiting_implementation_receives_it_and_concludes(self):
		"""The story's Then, and the point of the whole change."""
		inst = self._waiting_instance(IMPL_A)
		model = self._model(
			"WI2090 Deployed A", "wi2090_dep_a", _trivial_xml("wi2090_dep_a"), implementation=IMPL_A
		)

		delivered = send_process_model_deployed_message(model)

		self.assertEqual(delivered, [inst.name])
		inst.reload()
		self.assertEqual(
			inst.status,
			"Completed",
			"the implementation should have run past its catch event to the end",
		)

	def test_the_payload_reaches_the_implementation(self):
		"""So the map can branch on which model was deployed, and by whom."""
		inst = self._waiting_instance(IMPL_A)
		model = self._model(
			"WI2090 Payload", "wi2090_payload", _trivial_xml("wi2090_payload"), implementation=IMPL_A
		)
		model.db_set("version", 7, update_modified=False)
		model.reload()

		send_process_model_deployed_message(model)

		inst.reload()
		data = json.loads(inst.workflow_state or "{}").get("data") or {}
		self.assertEqual(data.get("process_model"), "WI2090 Payload")
		self.assertEqual(data.get("process_implementation"), IMPL_A)
		self.assertEqual(data.get("version"), 7)
		self.assertTrue(data.get("deployed_by"))

	def test_only_the_commissioning_implementation_is_told(self):
		"""Two implementations waiting; a deployment answers only its own."""
		mine = self._waiting_instance(IMPL_A)
		other = self._waiting_instance(IMPL_B)
		model = self._model(
			"WI2090 Scoped", "wi2090_scoped", _trivial_xml("wi2090_scoped"), implementation=IMPL_A
		)

		delivered = send_process_model_deployed_message(model)

		self.assertEqual(delivered, [mine.name])
		other.reload()
		self.assertEqual(other.status, "Active", "the unrelated implementation must be untouched")

	def test_an_instance_not_at_a_catch_event_is_skipped_quietly(self):
		"""An implementation map that never grew a catch event for this message
		is the normal case, not a failure: the deploy must survive it."""
		inst = self._waiting_instance(IMPL_A, message_name="Something_Else_Action")
		model = self._model(
			"WI2090 Uncaught", "wi2090_uncaught", _trivial_xml("wi2090_uncaught"), implementation=IMPL_A
		)

		delivered = send_process_model_deployed_message(model)

		self.assertEqual(delivered, [])
		inst.reload()
		self.assertEqual(inst.status, "Active")

	def test_deploying_through_the_real_path_announces_it(self):
		"""Wired into compile_process_model — the Deploy button's own endpoint —
		not just callable in isolation."""
		inst = self._waiting_instance(IMPL_A)
		model = self._model(
			"WI2090 Real Deploy",
			"wi2090_real",
			_trivial_xml("wi2090_real"),
			implementation=IMPL_A,
		)

		result = compile_process_model(model.name)

		self.assertTrue(result.get("success"))
		inst.reload()
		self.assertEqual(
			inst.status,
			"Completed",
			"deploying the model should have concluded the waiting implementation",
		)

	def test_deploy_still_succeeds_when_delivery_blows_up(self):
		"""A deploy is not undone because the announcement failed.

		The failure is injected at receive_message — the actual thing that can
		break — rather than by patching frappe.get_all, which is used by the
		whole trigger module and poisons unrelated machinery mid-test.
		"""
		from unittest.mock import patch

		inst = self._waiting_instance(IMPL_A)
		model = self._model(
			"WI2090 Boom", "wi2090_boom", _trivial_xml("wi2090_boom"), implementation=IMPL_A
		)

		target = (
			"one_bpmn.one_bpmn.doctype.bpmn_process_instance."
			"bpmn_process_instance.BPMNProcessInstance.receive_message"
		)
		with patch(target, side_effect=RuntimeError("engine on fire")):
			self.assertEqual(send_process_model_deployed_message(model), [])
			# And the deploy itself still goes through.
			self.assertTrue(compile_process_model(model.name).get("success"))

		inst.reload()
		self.assertEqual(inst.status, "Active", "a failed announcement must not disturb the instance")
