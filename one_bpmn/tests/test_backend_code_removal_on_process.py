# WI-003131: backend code removal tracking moves from BPMN Process Model to Process.
#
# The deploy warning and the pre-deploy readiness check both used to read
# backend_code_removal_status off the model being deployed, so every new
# version of a process's diagram started back at "Not Started" and the
# warning fired again even though nothing about the backend had changed.
# The field now lives once on the Process; these tests cover:
#   - compile_process_model's warning, read from the model's Process, for
#     each status;
#   - a model with no process_name deploying with no warning and no error;
#   - the pre_model_sync patch that backfills the Process from its models.

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.api.compilation import compile_process_model
from one_bpmn.one_bpmn.patches.v1_0 import move_backend_code_removal_to_process as patch


def _trivial_xml(process_id: str) -> str:
	return f"""<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
                  id="Defs_{process_id}" targetNamespace="http://bpmn.io/schema/bpmn">
  <bpmn:process id="{process_id}" isExecutable="true">
    <bpmn:startEvent id="s"><bpmn:outgoing>f1</bpmn:outgoing></bpmn:startEvent>
    <bpmn:sequenceFlow id="f1" sourceRef="s" targetRef="e" />
    <bpmn:endEvent id="e"><bpmn:incoming>f1</bpmn:incoming></bpmn:endEvent>
  </bpmn:process>
</bpmn:definitions>"""


class _ProcessAndModelFixtures(FrappeTestCase):
	def setUp(self):
		self._models: list[str] = []
		self._processes: list[str] = []

	def tearDown(self):
		for name in self._models:
			if frappe.db.exists("BPMN Process Model", name):
				frappe.delete_doc("BPMN Process Model", name, force=True, ignore_permissions=True)
		for name in self._processes:
			if frappe.db.exists("Process", name):
				frappe.delete_doc("Process", name, force=True, ignore_permissions=True)

	def _process(self, name, status=None, notes=None):
		if frappe.db.exists("Process", name):
			frappe.delete_doc("Process", name, force=True, ignore_permissions=True)
		doc = frappe.new_doc("Process")
		doc.process_name = name
		doc.description = f"Fixture process {name}"
		doc.process_owner = "Administrator"
		if status is not None:
			doc.backend_code_removal_status = status
		if notes is not None:
			doc.backend_code_removal_notes = notes
		doc.insert(ignore_permissions=True)
		self._processes.append(name)
		return doc

	def _model(self, name, process_id, process_name=None):
		if frappe.db.exists("BPMN Process Model", name):
			frappe.delete_doc("BPMN Process Model", name, force=True, ignore_permissions=True)
		doc = frappe.new_doc("BPMN Process Model")
		doc.name = name
		doc.title = name
		doc.process_id = process_id
		doc.bpmn_xml = _trivial_xml(process_id)
		doc.version = 1
		if process_name:
			doc.process_name = process_name
		doc.flags.ignore_permissions = True
		doc.insert(ignore_permissions=True)
		self._models.append(name)
		return doc

	@staticmethod
	def _has_backend_warning(result):
		return any(w.get("label") == "Backend Code Removal" for w in result.get("warnings", []))


class TestDeployWarningReadsTheProcess(_ProcessAndModelFixtures):
	def test_not_started_warns(self):
		proc = self._process(f"WI3131 Proc NS {frappe.generate_hash(length=6)}", status="Not Started")
		model = self._model(f"WI3131 Model NS {frappe.generate_hash(length=6)}", "wi3131_ns", proc.name)

		result = compile_process_model(model.name)

		self.assertTrue(self._has_backend_warning(result))

	def test_removed_on_ba_warns(self):
		proc = self._process(f"WI3131 Proc BA {frappe.generate_hash(length=6)}", status="Removed on BA")
		model = self._model(f"WI3131 Model BA {frappe.generate_hash(length=6)}", "wi3131_ba", proc.name)

		result = compile_process_model(model.name)

		self.assertTrue(self._has_backend_warning(result))

	def test_removed_on_production_does_not_warn(self):
		proc = self._process(
			f"WI3131 Proc Prod {frappe.generate_hash(length=6)}", status="Removed on Production"
		)
		model = self._model(f"WI3131 Model Prod {frappe.generate_hash(length=6)}", "wi3131_prod", proc.name)

		result = compile_process_model(model.name)

		self.assertFalse(self._has_backend_warning(result))

	def test_a_model_with_no_process_shows_no_warning_and_no_error(self):
		model = self._model(f"WI3131 Model NoProc {frappe.generate_hash(length=6)}", "wi3131_noproc")

		result = compile_process_model(model.name)

		self.assertTrue(result.get("success"))
		self.assertFalse(self._has_backend_warning(result))

	def test_changing_the_process_status_changes_every_model_version(self):
		"""One place: editing the Process, not any model, changes the result."""
		proc = self._process(f"WI3131 Proc Shared {frappe.generate_hash(length=6)}", status="Not Started")
		model_v1 = self._model(f"WI3131 Model V1 {frappe.generate_hash(length=6)}", "wi3131_v1", proc.name)
		model_v2 = self._model(f"WI3131 Model V2 {frappe.generate_hash(length=6)}", "wi3131_v2", proc.name)

		self.assertTrue(self._has_backend_warning(compile_process_model(model_v1.name)))
		self.assertTrue(self._has_backend_warning(compile_process_model(model_v2.name)))

		frappe.db.set_value("Process", proc.name, "backend_code_removal_status", "Removed on Production")

		self.assertFalse(self._has_backend_warning(compile_process_model(model_v1.name)))
		self.assertFalse(self._has_backend_warning(compile_process_model(model_v2.name)))


class TestMoveBackendCodeRemovalToProcessPatch(_ProcessAndModelFixtures):
	def test_mixed_statuses_take_the_most_advanced(self):
		proc = self._process(f"WI3131 Patch Mixed {frappe.generate_hash(length=6)}")
		self._model(f"WI3131 Patch M1 {frappe.generate_hash(length=6)}", "wi3131_patch_m1", proc.name)
		self._model(f"WI3131 Patch M2 {frappe.generate_hash(length=6)}", "wi3131_patch_m2", proc.name)

		model_names = [n for n in self._models if "Patch M1" in n or "Patch M2" in n]
		frappe.db.set_value(
			"BPMN Process Model", model_names[0], "backend_code_removal_status", "Removed on BA"
		)
		frappe.db.set_value(
			"BPMN Process Model", model_names[1], "backend_code_removal_status", "Not Started"
		)

		patch.execute()

		self.assertEqual(
			frappe.db.get_value("Process", proc.name, "backend_code_removal_status"), "Removed on BA"
		)

	def test_all_not_started_stays_not_started(self):
		proc = self._process(f"WI3131 Patch AllNS {frappe.generate_hash(length=6)}")
		self._model(f"WI3131 Patch AllNS M1 {frappe.generate_hash(length=6)}", "wi3131_allns_m1", proc.name)
		self._model(f"WI3131 Patch AllNS M2 {frappe.generate_hash(length=6)}", "wi3131_allns_m2", proc.name)

		patch.execute()

		self.assertEqual(
			frappe.db.get_value("Process", proc.name, "backend_code_removal_status"), "Not Started"
		)

	def test_notes_are_concatenated(self):
		proc = self._process(f"WI3131 Patch Notes {frappe.generate_hash(length=6)}")
		m1 = self._model(f"WI3131 Patch Notes M1 {frappe.generate_hash(length=6)}", "wi3131_notes_m1", proc.name)
		m2 = self._model(f"WI3131 Patch Notes M2 {frappe.generate_hash(length=6)}", "wi3131_notes_m2", proc.name)
		frappe.db.set_value("BPMN Process Model", m1.name, "backend_code_removal_notes", "ticket A")
		frappe.db.set_value("BPMN Process Model", m2.name, "backend_code_removal_notes", "ticket B")

		patch.execute()

		notes = frappe.db.get_value("Process", proc.name, "backend_code_removal_notes")
		self.assertIn("ticket A", notes)
		self.assertIn("ticket B", notes)

	def test_running_the_patch_twice_changes_nothing_further(self):
		proc = self._process(f"WI3131 Patch Idem {frappe.generate_hash(length=6)}")
		model = self._model(f"WI3131 Patch Idem M1 {frappe.generate_hash(length=6)}", "wi3131_idem_m1", proc.name)
		frappe.db.set_value(
			"BPMN Process Model", model.name, "backend_code_removal_status", "Removed on Production"
		)
		frappe.db.set_value("BPMN Process Model", model.name, "backend_code_removal_notes", "settled")

		patch.execute()
		first_status = frappe.db.get_value("Process", proc.name, "backend_code_removal_status")
		first_notes = frappe.db.get_value("Process", proc.name, "backend_code_removal_notes")

		patch.execute()

		self.assertEqual(
			frappe.db.get_value("Process", proc.name, "backend_code_removal_status"), first_status
		)
		self.assertEqual(
			frappe.db.get_value("Process", proc.name, "backend_code_removal_notes"), first_notes
		)
