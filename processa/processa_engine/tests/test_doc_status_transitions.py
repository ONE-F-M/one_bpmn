# Copyright (c) 2026, one-fm and contributors
"""Deploy refuses an Apply Workflow task whose document status Frappe does not allow after the previous one."""

from itertools import pairwise
from pathlib import Path

import frappe
from frappe.tests.utils import FrappeTestCase

from processa.api.deploy import compile_process_model
from processa.processa_engine.compiler.doc_status import doc_status_transition_errors

MODEL = "Doc Status Transitions Test Model"
CASES_XML = (Path(__file__).parent / "fixtures" / "doc_status_cases.bpmn").read_text()

FLAGGED = [
	"Draft to Cancelled: then Cancelled",
	"Submitted to Draft: then Draft",
	"Cancelled to Submitted: then Submitted",
	"Cancelled to Draft: then Draft",
	"Cancelled to Cancelled: then Cancelled",
	"Gateway path: then Cancelled",
	"Boundary path: then Draft",
	"Into subprocess: inside Cancelled",
	"Out of subprocess: then Draft",
	"Through empty subprocess: then Cancelled",
	"Subprocess boundary: then Submitted",
]


class TestDocStatusTransitions(FrappeTestCase):
	def _model(self, xml: str, process_id: str):
		if frappe.db.exists("BPMN Process Model", MODEL):
			frappe.delete_doc("BPMN Process Model", MODEL, force=1)
		doc = frappe.new_doc("BPMN Process Model")
		doc.name = MODEL
		doc.title = MODEL
		doc.process_id = process_id
		doc.bpmn_xml = xml
		doc.version = 1
		doc.insert()

	def test_every_case_in_the_fixture_is_judged_like_frappe(self):
		errors = doc_status_transition_errors(CASES_XML)

		flagged = sorted(error.split('"')[1] for error in errors)
		self.assertEqual(flagged, sorted(FLAGGED))

	def test_deploy_refuses_a_forbidden_change(self):
		self._model(_chain_xml("0", "2"), "doc_status_chain")

		with self.assertRaises(frappe.ValidationError) as raised:
			compile_process_model(MODEL)

		self.assertIn("Frappe does not allow Draft (0) to Cancelled (2)", str(raised.exception))
		self.assertFalse(frappe.db.get_value("BPMN Process Model", MODEL, "serialized_spec"))

	def test_deploy_refuses_the_cases_model(self):
		self._model(CASES_XML, "doc_status_cases")

		with self.assertRaises(frappe.ValidationError) as raised:
			compile_process_model(MODEL)

		for name in FLAGGED:
			self.assertIn(f'"{name}"', str(raised.exception))

	def test_allowed_changes_deploy(self):
		self._model(_chain_xml("0", "0", "1", "1", "2"), "doc_status_chain")

		self.assertTrue(compile_process_model(MODEL)["success"])


def _chain_xml(*statuses: str) -> str:
	"""A start event, one Apply Workflow task per status in order, and an end event."""
	ids = ["s", *[f"t{i}" for i in range(len(statuses))], "e"]
	tasks = "".join(
		f'<bpmn:serviceTask id="t{i}" name="Step {i}" spiffworkflow:serviceType="apply_workflow" '
		f'spiffworkflow:serviceTargetDoctype="Doc Status Test Doctype" spiffworkflow:docStatus="{status}" />'
		for i, status in enumerate(statuses)
	)
	flows = "".join(
		f'<bpmn:sequenceFlow id="f{i}" sourceRef="{a}" targetRef="{b}" />'
		for i, (a, b) in enumerate(pairwise(ids))
	)
	return f"""<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
    xmlns:spiffworkflow="http://spiffworkflow.org/bpmn/schema/1.0/core" id="Defs_doc_status">
  <bpmn:process id="doc_status_chain" isExecutable="true">
    <bpmn:startEvent id="s" />{tasks}<bpmn:endEvent id="e" />{flows}
  </bpmn:process>
</bpmn:definitions>"""
