# Copyright (c) 2026, one-fm and contributors
# WI-001348 (1-01): Register Ad-hoc Subprocess parsing in the compile pipeline.
#
# SpiffWorkflow 3.1.x registers <bpmn:adHocSubProcess> in BpmnParser.PARSER_CLASSES
# and ships AdHocSubprocessSpec/AdHocSubprocess converters in the serializer's
# DEFAULT_CONFIG. These tests verify one_bpmn's compile pipeline (parse_bpmn →
# create_workflow → serialize/restore) exercises that support end to end.

from __future__ import annotations

import json
from pathlib import Path

from frappe.tests.utils import FrappeTestCase
from SpiffWorkflow.bpmn.parser.ValidationException import ValidationException
from SpiffWorkflow.bpmn.specs.bpmn_process_spec import AdHocSubprocessSpec
from SpiffWorkflow.util.task import TaskState

from one_bpmn.one_bpmn import engine

FIXTURES = Path(__file__).parent / "fixtures"
ADHOC_PROCESS_ID = "Process_AdhocThree"
REFERENCE_PROCESS_ID = "main"


def _started_subprocesses(wf):
	wf.do_engine_steps()
	return list(wf.subprocesses.values())


class TestAdhocSubprocessParsing(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.adhoc_xml = (FIXTURES / "adhoc_three_tasks.bpmn").read_text()
		cls.reference_xml = (FIXTURES / "adhoc_reference.bpmn").read_text()
		cls.sequential_xml = (FIXTURES / "simple_sequential.bpmn").read_text()

	# ── Scenario 1: compile succeeds, attributes survive serialization ──

	def test_parse_bpmn_compiles_adhoc_diagram(self):
		spec_dict, _ = engine.parse_bpmn(self.adhoc_xml, ADHOC_PROCESS_ID)
		self.assertIsInstance(spec_dict, dict)
		# JSON-safe: storable in BPMN Process Model.serialized_spec
		json.dumps(spec_dict)
		self.assertEqual(
			spec_dict["spec"]["task_specs"]["AdhocSub_1"]["typename"], "AdHocSubprocess"
		)

	def test_completion_condition_and_cancel_remaining_survive(self):
		spec_dict, _ = engine.parse_bpmn(self.adhoc_xml, ADHOC_PROCESS_ID)
		adhoc = spec_dict["subprocess_specs"]["AdhocSub_1"]
		self.assertEqual(adhoc["typename"], "AdHocSubprocessSpec")
		self.assertEqual(adhoc["completion_condition"], "done")
		# cancelRemainingInstances="false" in the XML; SpiffWorkflow defaults to
		# True, so False proves the attribute was parsed rather than defaulted.
		self.assertIs(adhoc["cancel_remaining"], False)

	def test_reference_diagram_with_loops_compiles(self):
		# SpiffWorkflow's own ad-hoc reference shape: standard loops, a
		# multi-instance task, a conditional gateway and a connected chain.
		spec_dict, _ = engine.parse_bpmn(self.reference_xml, REFERENCE_PROCESS_ID)
		adhoc = spec_dict["subprocess_specs"]["subprocess"]
		self.assertEqual(adhoc["completion_condition"], "done")
		self.assertIs(adhoc["cancel_remaining"], True)  # attribute absent → default

	# ── Scenario 2: create_workflow activates an AdHocSubprocess ──

	def test_create_workflow_activates_adhoc_subprocess(self):
		spec_dict, sp_specs = engine.parse_bpmn(self.adhoc_xml, ADHOC_PROCESS_ID)
		wf = engine.create_workflow(spec_dict, sp_specs)
		subprocesses = _started_subprocesses(wf)
		self.assertEqual(len(subprocesses), 1)
		self.assertIsInstance(subprocesses[0].spec, AdHocSubprocessSpec)

	# ── Scenario 3: no-input inner tasks are scheduled READY ──

	def test_unconditional_no_input_tasks_ready_on_entry(self):
		spec_dict, sp_specs = engine.parse_bpmn(self.adhoc_xml, ADHOC_PROCESS_ID)
		wf = engine.create_workflow(spec_dict, sp_specs)
		subprocess = _started_subprocesses(wf)[0]
		ready = {t.task_spec.name for t in subprocess.get_tasks(state=TaskState.READY)}
		# AdHocSubprocessSpec.create_paths() connects every unconditional
		# no-input task to start, so all three are READY at entry.
		self.assertEqual(ready, {"task_a", "task_b", "task_c"})

	def test_conditional_inner_tasks_not_started_at_entry(self):
		# Loop/multi-instance/gateway tasks with no inputs become conditional
		# paths (started by path_complete when their condition warrants), NOT
		# start-connected tasks. 1-03's dispatch loop builds on this split.
		spec_dict, sp_specs = engine.parse_bpmn(self.reference_xml, REFERENCE_PROCESS_ID)
		wf = engine.create_workflow(spec_dict, sp_specs)
		subprocess = _started_subprocesses(wf)[0]
		ready = {t.task_spec.name for t in subprocess.get_tasks(state=TaskState.READY)}
		self.assertEqual(ready, {"research"})
		self.assertEqual(
			{s.name for s in subprocess.spec.conditional_paths},
			{"revise", "edit", "make_graphics", "Gateway_1bp40us"},
		)

	# ── Scenario 4: deterministic serialization ──

	def test_double_compile_is_byte_identical(self):
		first, _ = engine.parse_bpmn(self.adhoc_xml, ADHOC_PROCESS_ID)
		second, _ = engine.parse_bpmn(self.adhoc_xml, ADHOC_PROCESS_ID)
		self.assertEqual(json.dumps(first), json.dumps(second))

	def test_double_compile_deterministic_for_existing_types(self):
		# No regression: plain diagrams compile deterministically too.
		first, _ = engine.parse_bpmn(self.sequential_xml, "Process_Sequential")
		second, _ = engine.parse_bpmn(self.sequential_xml, "Process_Sequential")
		self.assertEqual(json.dumps(first), json.dumps(second))

	def test_double_compile_deterministic_with_loops(self):
		first, _ = engine.parse_bpmn(self.reference_xml, REFERENCE_PROCESS_ID)
		second, _ = engine.parse_bpmn(self.reference_xml, REFERENCE_PROCESS_ID)
		self.assertEqual(json.dumps(first), json.dumps(second))

	# ── Pipeline round-trip and upstream guards ──

	def test_serialize_restore_round_trip_preserves_adhoc_state(self):
		spec_dict, sp_specs = engine.parse_bpmn(self.adhoc_xml, ADHOC_PROCESS_ID)
		wf = engine.create_workflow(spec_dict, sp_specs)
		wf.do_engine_steps()

		state = engine.serialize_workflow(wf)
		restored = engine.restore_workflow(json.loads(json.dumps(state)))

		subprocesses = list(restored.subprocesses.values())
		self.assertEqual(len(subprocesses), 1)
		self.assertIsInstance(subprocesses[0].spec, AdHocSubprocessSpec)
		ready = {
			t.task_spec.name for t in subprocesses[0].get_tasks(state=TaskState.READY)
		}
		self.assertEqual(ready, {"task_a", "task_b", "task_c"})

	def test_sequential_ordering_attribute_rejected(self):
		# SpiffWorkflow's AdHocParser rejects ordering="sequential" outright.
		# one_bpmn's sequential enforcement (WI-001350) lives in its own dispatch
		# loop instead — diagrams must NOT carry this attribute.
		xml = self.adhoc_xml.replace(
			'cancelRemainingInstances="false"',
			'cancelRemainingInstances="false" ordering="sequential"',
		)
		with self.assertRaises(ValidationException):
			engine.parse_bpmn(xml, ADHOC_PROCESS_ID)

	def test_sequential_ordering_rejected_with_spec_casing(self):
		# The BPMN enum value is "Sequential" (capitalized); upstream only
		# checks lowercase, so one_bpmn's parser normalizes before comparing.
		xml = self.adhoc_xml.replace(
			'cancelRemainingInstances="false"',
			'cancelRemainingInstances="false" ordering="Sequential"',
		)
		with self.assertRaises(ValidationException):
			engine.parse_bpmn(xml, ADHOC_PROCESS_ID)
