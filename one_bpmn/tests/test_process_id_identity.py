"""The record owns the process id; the diagram is rewritten to match.

The id used to be copied out of the diagram onto the record on every save. The
editor mints an id for a blank diagram without asking the record what it is
called, so the readable id a model was created with was overwritten the first
time anyone opened and saved it. On the BA site that left 65 of 127 registered
models with a generated id and 38 sharing one default — the value a Call
Activity resolves its target against.

Run with:
    bench --site SITE run-tests --app one_bpmn --module one_bpmn.tests.test_process_id_identity
"""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.one_bpmn.doctype.bpmn_process_model.bpmn_process_model import (
	new_process_id,
	swap_process_id,
	xml_process_id,
)


def _diagram(process_id: str, calls: str = "") -> str:
	called = f'<bpmn:callActivity id="c1" calledElement="{calls}" />' if calls else ""
	return (
		'<?xml version="1.0" encoding="UTF-8"?>'
		'<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"'
		' xmlns:bpmndi="http://www.omg.org/spec/BPMN/20100524/DI">'
		f'<bpmn:process id="{process_id}" isExecutable="true">{called}</bpmn:process>'
		'<bpmndi:BPMNDiagram id="d1">'
		f'<bpmndi:BPMNPlane id="p1" bpmnElement="{process_id}" />'
		"</bpmndi:BPMNDiagram></bpmn:definitions>"
	)


class TestSwappingAnIdInADiagram(FrappeTestCase):
	def test_it_moves_the_process_and_the_plane_that_draws_it(self):
		out = swap_process_id(_diagram("Process_1"), "Process_1", "leave_request_ab12cd34")

		self.assertEqual(xml_process_id(out), "leave_request_ab12cd34")
		self.assertIn('bpmnElement="leave_request_ab12cd34"', out)
		self.assertNotIn("Process_1", out)

	def test_it_moves_a_call_activity_that_names_the_id(self):
		out = swap_process_id(_diagram("caller_1", calls="Process_1"), "Process_1", "renamed_9f")

		self.assertIn('calledElement="renamed_9f"', out)

	def test_it_leaves_a_longer_id_that_merely_starts_the_same_alone(self):
		"""The bug this guards: a plain string replace turns Process_10 into <new>0."""
		out = swap_process_id(_diagram("Process_10"), "Process_1", "renamed_9f")

		self.assertEqual(xml_process_id(out), "Process_10")
		self.assertNotIn("renamed_9f", out)

	def test_swapping_an_id_for_itself_changes_nothing(self):
		xml = _diagram("Process_1")

		self.assertEqual(swap_process_id(xml, "Process_1", "Process_1"), xml)


class TestTheRecordOwnsTheId(FrappeTestCase):
	"""A save must not let the diagram rename the record."""

	def _model(self, **kwargs):
		doc = frappe.new_doc("BPMN Process Model")
		doc.update(kwargs)
		doc.flags.skip_editability_check = True
		doc.flags.skip_script_security_check = True
		doc.flags.skip_process_id_regeneration = True
		return doc

	def test_a_diagram_that_disagrees_is_rewritten_to_the_record(self):
		doc = self._model(
			title=f"Identity {frappe.generate_hash(length=6)}",
			process_id="leave_request_ab12cd34",
			bpmn_xml=_diagram("Process_c0ffee00"),
		)
		doc.sync_process_id_with_xml()

		self.assertEqual(doc.process_id, "leave_request_ab12cd34")
		self.assertEqual(xml_process_id(doc.bpmn_xml), "leave_request_ab12cd34")

	def test_a_record_with_no_id_yet_takes_the_diagram_s(self):
		"""The import case — there the file carries the identity."""
		doc = self._model(
			title=f"Imported {frappe.generate_hash(length=6)}",
			process_id="",
			bpmn_xml=_diagram("purchase_order_7a"),
		)
		doc.sync_process_id_with_xml()

		self.assertEqual(doc.process_id, "purchase_order_7a")

	def test_a_new_id_is_named_after_its_process(self):
		self.assertTrue(new_process_id("Leave Request").startswith("leave_request_"))
		self.assertNotEqual(new_process_id("Leave Request"), new_process_id("Leave Request"))
