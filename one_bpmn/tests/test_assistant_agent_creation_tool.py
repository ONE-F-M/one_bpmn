# Copyright (c) 2026, one-fm and contributors
# WI-001751: the AI Assistant's agent-creation tool shape.
#
# Agent creation used to exist only on the modal path (a proposed_config the
# designer confirmed with a button), which is a single LLM call with no tool loop
# — so the assistant could never follow creation with anything, least of all
# building the agent's evals. As a shape in the tools sub-process, creation and
# eval authoring become reachable in one conversation.
#
# As with the eval tools, the thing worth pinning is the round trip: the XML the
# patch splices in must survive _extract_tool_shapes with its argument schema
# intact. A shape whose aiToolParams fails to parse still compiles — it just
# silently becomes a zero-argument tool the model cannot pass anything to.

from __future__ import annotations

from xml.etree import ElementTree

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.agents.shape_tools import compile_shape_tools
from one_bpmn.api.compilation import _extract_tool_shapes
from one_bpmn.one_bpmn.patches.v1_0.add_assistant_agent_creation_tool import (
	_PROMPT_MARKER,
	_PROMPT_SECTION,
	_STALE_PHRASES,
	_TOOL_SHAPE,
	_shape_xml,
)

BPMN_NS = "http://www.omg.org/spec/BPMN/20100524/MODEL"
SPIFF_NS = "http://spiffworkflow.org/bpmn/schema/1.0/core"


def _adhoc():
	xml = (
		f'<bpmn:adHocSubProcess xmlns:bpmn="{BPMN_NS}" xmlns:spiffworkflow="{SPIFF_NS}" '
		'id="lumina_tools" name="Lumina Tools">'
		f"{_shape_xml(_TOOL_SHAPE)}"
		"<bpmn:completionCondition>True</bpmn:completionCondition>"
		"</bpmn:adHocSubProcess>"
	)
	return ElementTree.fromstring(xml)


class TestAssistantAgentCreationTool(FrappeTestCase):
	def test_generated_xml_is_well_formed(self):
		self.assertIsNotNone(_adhoc())

	def test_shape_extracts_as_a_tool_descriptor(self):
		shapes = _extract_tool_shapes(_adhoc(), BPMN_NS, SPIFF_NS)
		self.assertEqual([s["bpmn_id"] for s in shapes], ["create_agent_configuration"])
		self.assertTrue(shapes[0]["description"])
		self.assertTrue(shapes[0]["serverScript"])

	def test_argument_schema_survives_the_round_trip(self):
		shape = _extract_tool_shapes(_adhoc(), BPMN_NS, SPIFF_NS)[0]
		self.assertEqual(
			sorted(shape["parameters"]),
			[
				"agent_framework",
				"agent_name",
				"ai_model",
				"chat_mode_label",
				"description",
				"process_model",
				"system_prompt",
			],
		)
		# What the creation process's Validate step demands has to be mandatory
		# here, or the model calls the tool and gets an error back instead of
		# asking the designer. system_prompt is NOT required: the process
		# generates it from description when empty. chat_mode_label is NOT
		# required either (WI-001997): a process-embedded agent (non-chat
		# process_model) needs no label, so the tool script and the endpoint
		# enforce the label conditionally instead of the schema.
		self.assertEqual(
			sorted(shape["required"]),
			["agent_name", "ai_model"],
		)

	def test_contract_asks_for_a_model_not_a_provider(self):
		"""WI-001655 made the model the agent's pick, with the provider derived
		from that model's credentials link. Offering a provider field would leave
		ai_model empty and fail validation, landing the agent in Needs Attention."""
		shape = _extract_tool_shapes(_adhoc(), BPMN_NS, SPIFF_NS)[0]
		self.assertIn("ai_model", shape["parameters"])
		self.assertNotIn("ai_provider_credentials", shape["parameters"])
		self.assertNotIn("aiProvider", shape["parameters"])
		self.assertEqual(
			shape["parameters"]["agent_framework"]["enum"],
			["Direct API", "Google ADK", "LangGraph", "Anthropic"],
		)

	def test_sample_prompts_are_not_part_of_the_contract(self):
		"""Evals belong in a suite with its own cases, not duplicated onto the
		configuration — so the model must not be offered a place to put them."""
		shape = _extract_tool_shapes(_adhoc(), BPMN_NS, SPIFF_NS)[0]
		self.assertNotIn("sample_prompts", shape["parameters"])

	def test_descriptor_compiles_into_a_callable_tool(self):
		shapes = _extract_tool_shapes(_adhoc(), BPMN_NS, SPIFF_NS)
		instance = frappe._dict(_service_task_extensions={}, context_doctype="", context_docname="")
		tools = compile_shape_tools(shapes, instance)
		self.assertEqual([t.name for t in tools], ["create_agent_configuration"])
		self.assertTrue(callable(tools[0].fn))
		self.assertTrue(tools[0].parameters)
		self.assertFalse(getattr(tools[0], "human", False))

	def test_documentation_warns_that_it_writes_immediately(self):
		"""On the modal path a button press was the confirmation gate. A tool call
		has none, so the description has to carry that weight."""
		doc = _TOOL_SHAPE["documentation"].lower()
		self.assertIn("real record", doc)
		self.assertIn("confirm", doc)

	def test_prompt_section_carries_its_own_marker(self):
		"""_steer_prompt skips on the marker, so the appended text must contain it
		or every migrate would append another copy."""
		self.assertIn(_PROMPT_MARKER, _PROMPT_SECTION)

	def test_prompt_orders_creation_before_evals(self):
		section = _PROMPT_SECTION
		self.assertIn("CREATE THE AGENT FIRST", section)
		self.assertLess(
			section.index("create_agent_configuration"),
			section.index("whether they want evals"),
		)

	def test_prompt_requires_confirmation_before_creating(self):
		self.assertIn("CONFIRM BEFORE CREATING", _PROMPT_SECTION)

	def test_prompt_tells_the_model_to_pick_a_model_not_a_provider(self):
		self.assertIn("AI Model catalog", _PROMPT_SECTION)
		self.assertIn("derived from the model's credentials link", _PROMPT_SECTION)

	def test_required_args_match_the_creation_validation_rules(self):
		"""Guard against the contract drifting from what provisioning demands —
		exactly the drift that made an earlier version of this tool produce
		agents with no model."""
		from one_bpmn.agents.agent_provisioning import VALIDATION_RULES

		rule_fields = {r["field"] for r in VALIDATION_RULES}
		shape = _extract_tool_shapes(_adhoc(), BPMN_NS, SPIFF_NS)[0]
		# ai_model is validated unconditionally and must be collected up front.
		self.assertIn("ai_model", rule_fields)
		self.assertIn("ai_model", shape["required"])
		# chat_mode_label is validated CONDITIONALLY (WI-001997: waived for
		# agents mapped to a non-chat process), so it stays in the schema but
		# out of required — the tool script enforces it when no map is given.
		self.assertIn("chat_mode_label", rule_fields)
		self.assertIn("chat_mode_label", shape["parameters"])
		self.assertNotIn("chat_mode_label", shape["required"])
		# The provider is derived, never supplied.
		self.assertIn("ai_provider_credentials", rule_fields)
		self.assertNotIn("ai_provider_credentials", shape["parameters"])

	def test_prompt_section_contains_no_stale_phrase(self):
		"""The repair map exists because an early draft pointed the model at the
		eval rules "below" when they are in fact above. The shipped text must not
		reintroduce any phrase the patch is repairing."""
		for stale in _STALE_PHRASES:
			self.assertNotIn(stale, _PROMPT_SECTION)

	def test_shape_bounds_sit_inside_the_tools_subprocess(self):
		"""lumina_tools occupies x 700-1400, y 290-850; a shape outside that box
		renders detached from the toolbox it belongs to."""
		x, y = _TOOL_SHAPE["bounds"]
		self.assertGreaterEqual(x, 700)
		self.assertLessEqual(x + 100, 1400)
		self.assertGreaterEqual(y, 290)
		self.assertLessEqual(y + 80, 850)

	def test_shape_does_not_collide_with_the_eval_tools(self):
		from one_bpmn.one_bpmn.patches.v1_0.add_assistant_eval_authoring_tools import (
			_ORPHAN_DI,
			_TOOL_SHAPES as EVAL_SHAPES,
		)

		taken = [s["bounds"] for s in EVAL_SHAPES] + [_ORPHAN_DI["bounds"]]
		self.assertNotIn(_TOOL_SHAPE["bounds"], taken)
