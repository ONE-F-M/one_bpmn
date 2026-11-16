"""The record owns the process id; the diagram is rewritten to match.

The id used to be copied out of the diagram onto the record on every save. The
editor mints an id for a blank diagram without asking the record what it is
called, so the readable id a model was created with was overwritten the first
time anyone opened and saved it. On the BA site that left 65 of 127 registered
models with a generated id and 38 sharing one default — the value a Call
Activity resolves its target against.

Run with:
    bench --site SITE run-tests --app processa --module processa.processa_engine.tests.test_process_id_identity
"""

from __future__ import annotations

import frappe
from frappe.tests import IntegrationTestCase, UnitTestCase

from processa.processa_engine.doctype.bpmn_process_model.bpmn_process_model import (
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


class TestSwappingAnIdInADiagram(UnitTestCase):
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


class TestTheRecordOwnsTheId(IntegrationTestCase):
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


class TestDeployWithAMismatch(IntegrationTestCase):
	"""The parser looks the process up by the id it is handed.

	Removing the old diagram-wins sync from deploy left a record whose diagram
	named something else unparseable — the exact failure the original comment
	there warned about. Deploy now reconciles the same way a save does.
	"""

	def setUp(self):
		self._models = []

	def tearDown(self):
		for name in self._models:
			if frappe.db.exists("BPMN Process Model", name):
				frappe.delete_doc("BPMN Process Model", name, force=1, ignore_permissions=True)

	def _model(self, name, process_id, xml):
		if frappe.db.exists("BPMN Process Model", name):
			frappe.delete_doc("BPMN Process Model", name, force=1, ignore_permissions=True)
		doc = frappe.new_doc("BPMN Process Model")
		doc.name = name
		doc.title = name
		doc.process_id = process_id
		doc.bpmn_xml = xml
		doc.version = 1
		doc.flags.ignore_permissions = True
		doc.flags.skip_process_id_regeneration = True
		doc.insert(ignore_permissions=True)
		self._models.append(name)
		return doc

	def test_a_diagram_that_disagrees_still_deploys(self):
		from processa.tests.test_call_activity import _child_xml

		name = f"PID Deploy {frappe.generate_hash(length=6)}"
		doc = self._model(name, "pid_deploy_owned", _child_xml(process_id="pid_deploy_owned"))
		# Reach past validate the way the repair patch and any direct write do.
		frappe.db.set_value(
			"BPMN Process Model", name,
			"bpmn_xml", _child_xml(process_id="Process_deadbeef"),
			update_modified=False,
		)

		from processa.api.deploy import compile_process_model

		compile_process_model(name)

		doc.reload()
		self.assertEqual(doc.process_id, "pid_deploy_owned")
		self.assertEqual(xml_process_id(doc.bpmn_xml), "pid_deploy_owned")

	def test_a_call_activity_still_resolves_after_its_target_is_renamed(self):
		from processa.api.deploy import compile_process_model
		from processa.tests.test_call_activity import _child_xml, _parent_xml

		tag = frappe.generate_hash(length=6)
		old_id = "Process_1"
		child = self._model(f"PID Child {tag}", old_id, _child_xml(process_id=old_id))
		parent = self._model(f"PID Parent {tag}", f"pid_parent_{tag}", _parent_xml(called=old_id, process_id=f"pid_parent_{tag}"))

		new_id = new_process_id("PID Child")
		frappe.db.set_value(
			"BPMN Process Model", child.name,
			{"process_id": new_id, "bpmn_xml": swap_process_id(child.bpmn_xml, old_id, new_id)},
			update_modified=False,
		)
		frappe.db.set_value(
			"BPMN Process Model", parent.name,
			"bpmn_xml", swap_process_id(parent.bpmn_xml, old_id, new_id),
			update_modified=False,
		)

		# The parent compiles only if its Call Activity still finds the child.
		compile_process_model(parent.name)
		parent.reload()
		self.assertIn(new_id, parent.serialized_spec or "")


class TestTheOtherWaysAModelIsCreated(IntegrationTestCase):
	def tearDown(self):
		for name in getattr(self, "_made", []):
			if frappe.db.exists("BPMN Process Model", name):
				frappe.delete_doc("BPMN Process Model", name, force=1, ignore_permissions=True)

	def test_an_import_keeps_the_id_the_file_carries(self):
		from processa.api.process_maps import import_bpmn
		from processa.tests.test_call_activity import _child_xml

		file_id = f"imported_{frappe.generate_hash(length=6)}"
		out = import_bpmn(xml_content=_child_xml(process_id=file_id), title=f"PID Import {file_id}")
		self._made = [out["name"]]

		self.assertEqual(frappe.db.get_value("BPMN Process Model", out["name"], "process_id"), file_id)

	def test_a_map_drawn_in_the_editor_is_named_after_its_process(self):
		from processa.api.process_maps import save_process_model
		from processa.tests.test_call_activity import _child_xml

		title = f"PID Editor {frappe.generate_hash(length=6)}"
		out = save_process_model(model_name=title, xml_content=_child_xml(process_id="Process_c0ffee11"))
		self._made = [out["name"]]

		doc = frappe.get_doc("BPMN Process Model", out["name"])
		self.assertTrue(doc.process_id.startswith("pid_editor_"), doc.process_id)
		self.assertEqual(xml_process_id(doc.bpmn_xml), doc.process_id)


class TestAnIdIsALegalXmlId(UnitTestCase):
	"""bpmn-js rejects an id that starts with a digit and draws the map as one collapsed pool."""

	def test_a_process_named_with_a_leading_digit_gets_a_letter_first(self):
		process_id = new_process_id("7 Days Absence Creation")

		self.assertTrue(process_id.startswith("p_7_days_absence_creation_"), process_id)
		self.assertRegex(process_id, r"^[A-Za-z_][\w.-]*$")

	def test_a_process_named_with_a_letter_keeps_its_plain_stem(self):
		self.assertTrue(new_process_id("Leave Request").startswith("leave_request_"))


class TestRepairingDigitLeadingIds(IntegrationTestCase):
	def setUp(self):
		from processa.patches.v1_0 import repair_digit_leading_process_ids

		self.patch = repair_digit_leading_process_ids
		self.old_id = f"7_days_{frappe.generate_hash(length=6)}"
		self.target = self._model(f"Digit Target {self.old_id}", self.old_id, _diagram(self.old_id))
		self.caller = self._model(
			f"Digit Caller {self.old_id}",
			f"caller_{self.old_id}",
			_diagram(f"caller_{self.old_id}", calls=self.old_id),
		)

	def _model(self, title, process_id, xml):
		doc = frappe.new_doc("BPMN Process Model")
		doc.update({"title": title, "process_id": process_id, "bpmn_xml": xml})
		doc.flags.skip_editability_check = True
		doc.flags.skip_script_security_check = True
		doc.flags.skip_process_id_regeneration = True
		doc.insert()
		self.addCleanup(frappe.delete_doc, "BPMN Process Model", doc.name, force=1)
		return doc.name

	def test_the_record_its_diagram_and_its_callers_move_to_the_prefixed_id(self):
		self.patch.execute()
		self.patch.execute()

		new_id = "p_" + self.old_id
		self.assertEqual(frappe.db.get_value("BPMN Process Model", self.target, "process_id"), new_id)
		self.assertEqual(
			xml_process_id(frappe.db.get_value("BPMN Process Model", self.target, "bpmn_xml")), new_id
		)
		self.assertIn(
			f'calledElement="{new_id}"', frappe.db.get_value("BPMN Process Model", self.caller, "bpmn_xml")
		)
		self.assertEqual(
			frappe.db.get_value("BPMN Process Model", self.caller, "process_id"), f"caller_{self.old_id}"
		)
