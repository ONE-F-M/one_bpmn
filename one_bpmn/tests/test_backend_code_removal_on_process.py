"""Backend code removal status is read from the Process, for every version of its process map."""

from __future__ import annotations

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.api.compilation import compile_process_model
from one_bpmn.one_bpmn.patches.v1_0 import move_backend_code_removal_to_process as move_patch


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
	def _process(self, prefix, status=None, notes=None):
		doc = frappe.new_doc("Process")
		doc.process_name = f"{prefix} {frappe.generate_hash(length=6)}"
		doc.description = "Backend code removal fixture"
		doc.process_owner = "Administrator"
		if status is not None:
			doc.backend_code_removal_status = status
		if notes is not None:
			doc.backend_code_removal_notes = notes
		return doc.insert()

	def _model(self, prefix, process_name=None):
		suffix = frappe.generate_hash(length=6)
		doc = frappe.new_doc("BPMN Process Model")
		doc.title = f"{prefix} {suffix}"
		doc.process_id = f"removal_{suffix}"
		doc.bpmn_xml = _trivial_xml(doc.process_id)
		doc.version = 1
		if process_name:
			doc.process_name = process_name
		doc.flags.skip_editability_check = True
		return doc.insert()

	@staticmethod
	def _has_backend_warning(result):
		return any(w.get("label") == "Backend Code Removal" for w in result.get("warnings", []))


class TestDeployWarningReadsTheProcess(_ProcessAndModelFixtures):
	def test_not_started_warns(self):
		proc = self._process("_Test Removal Proc NS", status="Not Started")
		model = self._model("_Test Removal Model NS", proc.name)

		result = compile_process_model(model.name)

		self.assertTrue(self._has_backend_warning(result))

	def test_removed_on_ba_warns(self):
		proc = self._process("_Test Removal Proc BA", status="Removed on BA")
		model = self._model("_Test Removal Model BA", proc.name)

		result = compile_process_model(model.name)

		self.assertTrue(self._has_backend_warning(result))

	def test_removed_on_production_does_not_warn(self):
		proc = self._process("_Test Removal Proc Prod", status="Removed on Production")
		model = self._model("_Test Removal Model Prod", proc.name)

		result = compile_process_model(model.name)

		self.assertFalse(self._has_backend_warning(result))

	def test_a_model_with_no_process_shows_no_warning_and_no_error(self):
		model = self._model("_Test Removal Model NoProc")

		result = compile_process_model(model.name)

		self.assertTrue(result.get("success"))
		self.assertFalse(self._has_backend_warning(result))

	def test_changing_the_process_status_changes_every_model_version(self):
		"""One place: editing the Process, not any model, changes the result."""
		proc = self._process("_Test Removal Proc Shared", status="Not Started")
		model_v1 = self._model("_Test Removal Model V1", proc.name)
		model_v2 = self._model("_Test Removal Model V2", proc.name)

		self.assertTrue(self._has_backend_warning(compile_process_model(model_v1.name)))
		self.assertTrue(self._has_backend_warning(compile_process_model(model_v2.name)))

		frappe.db.set_value("Process", proc.name, "backend_code_removal_status", "Removed on Production")

		self.assertFalse(self._has_backend_warning(compile_process_model(model_v1.name)))
		self.assertFalse(self._has_backend_warning(compile_process_model(model_v2.name)))


class TestMoveBackendCodeRemovalToProcessPatch(_ProcessAndModelFixtures):
	"""The model rows come from a mock: on a site built after this change the old model columns never exist."""

	def _run_patch(self, *rows):
		model_rows = [
			frappe._dict(process_name=p, backend_code_removal_status=s, backend_code_removal_notes=n)
			for p, s, n in rows
		]
		with patch.object(move_patch.frappe, "get_all", return_value=model_rows):
			move_patch.execute()

	def _removal(self, process_name):
		return frappe.db.get_value(
			"Process", process_name, ["backend_code_removal_status", "backend_code_removal_notes"]
		)

	def test_mixed_statuses_take_the_most_advanced(self):
		proc = self._process("_Test Removal Patch Mixed")
		self._run_patch((proc.name, "Not Started", None), (proc.name, "Removed on BA", None))
		self.assertEqual(self._removal(proc.name), ("Removed on BA", None))

	def test_all_not_started_stays_at_the_default(self):
		proc = self._process("_Test Removal Patch AllNS")
		self._run_patch((proc.name, "Not Started", None), (proc.name, "Not Started", ""))
		self.assertEqual(self._removal(proc.name), ("Not Started", None))

	def test_notes_are_joined_in_model_order(self):
		proc = self._process("_Test Removal Patch Notes")
		self._run_patch((proc.name, "Not Started", "ticket A "), (proc.name, "Not Started", "ticket B"))
		self.assertEqual(self._removal(proc.name), ("Not Started", "ticket A\nticket B"))

	def test_running_the_patch_twice_changes_nothing_further(self):
		proc = self._process("_Test Removal Patch Idem")
		rows = ((proc.name, "Removed on Production", "settled"),)
		self._run_patch(*rows)
		first = self._removal(proc.name)
		self._run_patch(*rows)
		self.assertEqual(self._removal(proc.name), first)
		self.assertEqual(first, ("Removed on Production", "settled"))

	def test_a_model_whose_process_is_gone_is_skipped(self):
		self._run_patch(("_Test Removal Missing Process", "Removed on BA", "x"))
		self.assertFalse(frappe.db.exists("Process", "_Test Removal Missing Process"))
