# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""A delegation tool is described by its target agent's CARD (WI-001933).

A shape that hands work to one of our agents used to be described to the
model by whatever the designer typed in its documentation. So which
specialist got picked came down to how well someone wrote a sentence — in
every map that reached the agent, each going stale separately.

Now the description is built from the agent's own card, the same one a
person reads on the A2A page, and read at run time so an edit reaches every
caller at once.

The rule that matters: an agent with no card gets no description written
for it. That is the same set the delegation itself would refuse, so the
model is never handed a description of a specialist it cannot reach.
"""

from __future__ import annotations

import json

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.agents import shape_tools
from one_bpmn.agents._eval_test_factories import make_agent_configuration
from one_bpmn.agents.a2a.card import tool_description
from one_bpmn.api.compilation import _extract_service_task_config, _resolve_ai_agent_tool_shapes


def _delegation_xml(
	agent: str, documentation: str = "", operation="delegate_to_local_agent", connector="a2a"
) -> str:
	params = json.dumps({"agent": agent, "instruction": "{{ task_data.instruction }}"})
	doc = f"<bpmn:documentation>{documentation}</bpmn:documentation>" if documentation else ""
	return f"""<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
    xmlns:spiffworkflow="http://spiffworkflow.org/bpmn/schema/1.0/core"
    id="Defs" targetNamespace="http://bpmn.io/schema/bpmn">
  <bpmn:process id="P1" isExecutable="true">
    <bpmn:serviceTask id="Agent_1" spiffworkflow:serviceType="ai_agent"
        spiffworkflow:aiToolsAdhoc="Tools_1" />
    <bpmn:adHocSubProcess id="Tools_1">
      <bpmn:serviceTask id="delegate_1" spiffworkflow:serviceType="connector"
          spiffworkflow:connectorId="{connector}"
          spiffworkflow:operation="{operation}"
          spiffworkflow:connectorParams='{params}'>{doc}</bpmn:serviceTask>
    </bpmn:adHocSubProcess>
  </bpmn:process>
</bpmn:definitions>"""


def _shapes(xml: str) -> list[dict]:
	svc = _extract_service_task_config(xml)
	_resolve_ai_agent_tool_shapes(xml, svc)
	return json.loads(svc["Agent_1"]["aiToolShapes"])


class TestTheCardIsTheToolDescription(FrappeTestCase):
	def test_the_card_carries_what_the_agent_is_for(self):
		worker = make_agent_configuration(
			a2a_exposed=1,
			a2a_skill_tags="safety, hse",
			description="Assesses site safety and writes up findings.",
		)
		text = tool_description(worker.name)
		self.assertIn("site safety", text.lower())
		self.assertIn("safety, hse", text)

	def test_sample_prompts_become_examples(self):
		worker = make_agent_configuration(a2a_exposed=1, description="Checks parts.")
		worker.append("sample_prompts", {"prompt": "Is the chiller pump in stock?"})
		worker.save(ignore_permissions=True)
		self.assertIn("chiller pump", tool_description(worker.name))

	def test_an_unexposed_agent_has_no_description_to_give(self):
		"""Not exposed is exactly the set delegation would refuse, so the
		model must not be told what it does."""
		hidden = make_agent_configuration(description="Does something private.")
		self.assertIsNone(tool_description(hidden.name))

	def test_a_draft_agent_has_no_description_to_give(self):
		draft = make_agent_configuration(a2a_exposed=1, lifecycle_status="Draft")
		self.assertIsNone(tool_description(draft.name))

	def test_an_unknown_agent_is_not_an_error(self):
		self.assertIsNone(tool_description("No Such Agent"))

	def test_the_designers_note_is_kept_below_the_card(self):
		"""The card says what the agent IS; the documentation is where a map
		says something true only here. Both survive, in that order."""
		worker = make_agent_configuration(a2a_exposed=1, description="Assesses site safety.")
		text = tool_description(worker.name, fallback="Only for Al Rai Tower.")
		self.assertLess(text.index("site safety"), text.index("Al Rai Tower"))
		self.assertIn("In this process: Only for Al Rai Tower.", text)


class TestExtractionFindsTheTarget(FrappeTestCase):
	def test_the_delegation_target_is_captured(self):
		shape = _shapes(_delegation_xml("Site Safety Assessor"))[0]
		self.assertEqual(shape["a2aAgent"], "Site Safety Assessor")

	def test_another_connector_is_left_alone(self):
		shape = _shapes(_delegation_xml("Whatever", connector="http"))[0]
		self.assertNotIn("a2aAgent", shape)

	def test_a_non_delegation_a2a_operation_is_left_alone(self):
		shape = _shapes(_delegation_xml("Whatever", operation="delegate_task"))[0]
		self.assertNotIn("a2aAgent", shape, "a remote hop has no local card to read")

	def test_a_templated_target_is_not_captured(self):
		"""Not known until the step runs, so there is no card to read at the
		moment the tool list is built."""
		shape = _shapes(_delegation_xml("{{ task_data.agent }}"))[0]
		self.assertNotIn("a2aAgent", shape)


class TestWhatTheModelIsShown(FrappeTestCase):
	def test_a_shape_with_no_documentation_still_describes_itself(self):
		"""The point of the change: the diagram says nothing, and the model
		still knows what the tool is for."""
		worker = make_agent_configuration(a2a_exposed=1, description="Assesses site safety.")
		tools = shape_tools.compile_shape_tools(_shapes(_delegation_xml(worker.name)), None)
		self.assertIn("site safety", tools[0].description.lower())

	def test_the_card_beats_the_documentation(self):
		worker = make_agent_configuration(a2a_exposed=1, description="Assesses site safety.")
		shapes = _shapes(_delegation_xml(worker.name, documentation="Ask about the thing."))
		description = shape_tools.compile_shape_tools(shapes, None)[0].description
		self.assertTrue(description.startswith(worker.chat_mode_label or worker.agent_name))

	def test_no_card_leaves_the_documentation_standing(self):
		hidden = make_agent_configuration(description="Private.")
		shapes = _shapes(_delegation_xml(hidden.name, documentation="Ask about the thing."))
		description = shape_tools.compile_shape_tools(shapes, None)[0].description
		self.assertEqual(description, "Ask about the thing.")

	def test_an_ordinary_tool_is_unaffected(self):
		xml = _delegation_xml("Whatever", documentation="Look up a customer.", connector="http")
		description = shape_tools.compile_shape_tools(_shapes(xml), None)[0].description
		self.assertEqual(description, "Look up a customer.")

	def test_editing_the_agent_changes_every_caller(self):
		"""Read at run time, not baked in at deploy: the shapes are compiled
		once and describe the agent differently afterwards."""
		worker = make_agent_configuration(a2a_exposed=1, description="Assesses site safety.")
		shapes = _shapes(_delegation_xml(worker.name))
		self.assertIn("site safety", shape_tools.compile_shape_tools(shapes, None)[0].description.lower())

		frappe.db.set_value("AI Agent Configuration", worker.name, "description", "Books contractors.")
		frappe.clear_document_cache("AI Agent Configuration", worker.name)
		self.assertIn("contractors", shape_tools.compile_shape_tools(shapes, None)[0].description.lower())


class TestTheSelectorSurfaceAgrees(FrappeTestCase):
	"""The AI Task Selector reads the same helper as the AI Agent Task.

	Worth its own test rather than trusting the shared call: the two surfaces
	build their tool lists in different modules, and the selector's used to be
	the one that quietly lost information the other had.
	"""

	def _subworkflow(self):
		from pathlib import Path

		from one_bpmn.one_bpmn import engine

		xml = (Path(__file__).parent / "fixtures" / "adhoc_three_tasks.bpmn").read_text()
		spec_dict, sp_specs = engine.parse_bpmn(xml, "Process_AdhocThree")
		wf = engine.create_workflow(spec_dict, sp_specs, initial_data={"done": False})
		wf.do_engine_steps()
		return next(iter(wf.subprocesses.values()))

	def test_a_delegating_step_is_described_by_its_card(self):
		from one_bpmn.agents.tool_pool import resolve_tool_pool

		worker = make_agent_configuration(a2a_exposed=1, description="Assesses site safety.")
		task_cfg = {"aiToolShapes": json.dumps([{"bpmn_id": "task_a", "a2aAgent": worker.name}])}
		by_name = {c.spec.name: c for c in resolve_tool_pool(self._subworkflow(), task_cfg)}
		self.assertIn("site safety", by_name["task_a"].spec.description.lower())

	def test_an_ordinary_step_keeps_its_documentation(self):
		from one_bpmn.agents.tool_pool import resolve_tool_pool

		by_name = {c.spec.name: c for c in resolve_tool_pool(self._subworkflow(), {})}
		self.assertNotIn("Good for:", by_name["task_a"].spec.description)
