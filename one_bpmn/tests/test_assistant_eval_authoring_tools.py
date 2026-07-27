# Copyright (c) 2026, one-fm and contributors
# WI-001751: the AI Assistant's eval-authoring tool shapes.
#
# The valuable thing to pin down is the round trip: the XML the patch splices
# into the assistant's ad-hoc sub-process must survive _extract_tool_shapes and
# come back out as tool descriptors carrying real argument schemas. A shape whose
# aiToolParams fails to parse still compiles — it just silently becomes a
# zero-argument tool the LLM cannot pass anything to, which is exactly the
# failure this guards.

from __future__ import annotations

from xml.etree import ElementTree

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.agents.shape_tools import compile_shape_tools
from one_bpmn.api.compilation import _extract_tool_shapes
from one_bpmn.one_bpmn.patches.v1_0.add_assistant_eval_authoring_tools import (
	_ORPHAN_DI,
	_PROMPT_MARKER,
	_PROMPT_SECTION,
	_TOOL_SHAPES,
	_di_xml,
	_escape_attr,
	_shape_xml,
)

BPMN_NS = "http://www.omg.org/spec/BPMN/20100524/MODEL"
SPIFF_NS = "http://spiffworkflow.org/bpmn/schema/1.0/core"


def _adhoc_with_tool_shapes() -> "ElementTree.Element":
	"""Wrap the patch's generated shapes in a minimal ad-hoc sub-process and
	parse it the way compilation.py sees the real diagram."""
	body = "".join(_shape_xml(s) for s in _TOOL_SHAPES)
	xml = (
		f'<bpmn:adHocSubProcess xmlns:bpmn="{BPMN_NS}" xmlns:spiffworkflow="{SPIFF_NS}" '
		'id="lumina_tools" name="Lumina Tools">'
		f"{body}"
		'<bpmn:completionCondition>True</bpmn:completionCondition>'
		"</bpmn:adHocSubProcess>"
	)
	return ElementTree.fromstring(xml)


class TestAssistantEvalToolShapes(FrappeTestCase):
	def test_generated_xml_is_well_formed(self):
		"""The escaped aiToolParams must not break the surrounding document."""
		self.assertIsNotNone(_adhoc_with_tool_shapes())

	def test_shapes_extract_as_tool_descriptors(self):
		shapes = _extract_tool_shapes(_adhoc_with_tool_shapes(), BPMN_NS, SPIFF_NS)
		self.assertEqual(
			[s["bpmn_id"] for s in shapes],
			["list_eval_suites", "create_eval_suite", "create_eval_case"],
		)
		for shape in shapes:
			# Description is the shape's documentation (Camunda convention) and is
			# what steers the model, so an empty one is a real defect.
			self.assertTrue(shape["description"], f"{shape['bpmn_id']} has no description")
			self.assertTrue(shape["serverScript"], f"{shape['bpmn_id']} has no Server Script")

	def test_argument_schemas_survive_the_round_trip(self):
		"""aiToolParams must arrive as parameters/required — not a zero-arg tool."""
		shapes = {s["bpmn_id"]: s for s in _extract_tool_shapes(_adhoc_with_tool_shapes(), BPMN_NS, SPIFF_NS)}

		self.assertEqual(shapes["list_eval_suites"]["required"], ["agent"])
		self.assertIn("agent", shapes["list_eval_suites"]["parameters"])

		create_suite = shapes["create_eval_suite"]
		self.assertEqual(sorted(create_suite["required"]), ["agent", "title"])
		self.assertEqual(
			sorted(create_suite["parameters"]),
			["agent", "description", "eval_type", "process_model", "title"],
		)
		# Direct vs Agent is the distinction WI-001751 introduced; the model has to
		# see both options or it cannot choose.
		self.assertEqual(create_suite["parameters"]["eval_type"]["enum"], ["Direct", "Agent"])

		create_case = shapes["create_eval_case"]
		self.assertEqual(sorted(create_case["required"]), ["input_user_prompt", "suite", "title"])
		assertion_items = create_case["parameters"]["assertions"]["items"]
		self.assertEqual(
			sorted(assertion_items["properties"]["assertion_type"]["enum"]),
			["contains", "equals", "llm_judge", "regex", "schema_valid"],
		)

	def test_descriptors_compile_into_callable_tools(self):
		shapes = _extract_tool_shapes(_adhoc_with_tool_shapes(), BPMN_NS, SPIFF_NS)
		instance = frappe._dict(_service_task_extensions={}, context_doctype="", context_docname="")
		tools = compile_shape_tools(shapes, instance)

		self.assertEqual(
			sorted(t.name for t in tools),
			["create_eval_case", "create_eval_suite", "list_eval_suites"],
		)
		for tool in tools:
			self.assertTrue(callable(tool.fn))
			self.assertTrue(tool.parameters, f"{tool.name} exposed no parameters to the LLM")
			self.assertFalse(getattr(tool, "human", False))

	def test_escape_attr_neutralises_quotes_and_angles(self):
		self.assertEqual(_escape_attr('a"b<c>d&e'), "a&#34;b&lt;c&gt;d&amp;e")

	def test_escape_attr_escapes_ampersand_before_entities(self):
		"""& must be escaped first, or the entities it introduces get mangled."""
		self.assertEqual(_escape_attr('&"'), "&amp;&#34;")

	def test_shapes_have_distinct_non_overlapping_bounds(self):
		"""Two shapes at the same coordinates render stacked and unclickable."""
		placed = [s["bounds"] for s in _TOOL_SHAPES] + [_ORPHAN_DI["bounds"]]
		self.assertEqual(len(placed), len(set(placed)))

	def test_di_stays_inside_the_adhoc_subprocess(self):
		"""lumina_tools occupies x 700-1400, y 290-850 on the assistant's map; a
		shape outside that box renders detached from the toolbox it belongs to."""
		for x, y in [s["bounds"] for s in _TOOL_SHAPES] + [_ORPHAN_DI["bounds"]]:
			self.assertGreaterEqual(x, 700)
			self.assertLessEqual(x + 100, 1400)
			self.assertGreaterEqual(y, 290)
			self.assertLessEqual(y + 80, 850)

	def test_di_xml_parses(self):
		xml = (
			'<bpmndi:BPMNPlane xmlns:bpmndi="http://www.omg.org/spec/BPMN/20100524/DI" '
			'xmlns:dc="http://www.omg.org/spec/DD/20100524/DC">'
			f'{_di_xml("list_eval_suites", 750, 730)}'
			"</bpmndi:BPMNPlane>"
		)
		self.assertIsNotNone(ElementTree.fromstring(xml))

	def test_prompt_section_carries_its_own_marker(self):
		"""_steer_prompt skips when the marker is present, so the section it
		appends must contain it or every migrate would append another copy."""
		self.assertIn(_PROMPT_MARKER, _PROMPT_SECTION)

	def test_prompt_section_orders_lookup_before_creation(self):
		"""The read-then-create order is the whole point of the three tools."""
		section = _PROMPT_SECTION
		self.assertLess(
			section.index("list_eval_suites"),
			section.index("create_eval_suite"),
		)
