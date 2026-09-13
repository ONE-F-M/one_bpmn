# Copyright (c) 2026, one-fm and contributors
"""A configuration must not keep overriding a map that was just imported with a
new prompt — the failure that left the BA site running a six-day-old Orchestrator
prompt after its map arrived with the change-request rule."""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.one_bpmn.patches.v1_0 import align_agent_prompts_with_their_maps as patch

AGENT = "Orchestrator Agent"
MAP_PROMPT = "You are the Orchestrator. Read the pull request first when changes were requested."


NS = ('xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL" '
      'xmlns:spiffworkflow="http://spiffworkflow.org/bpmn/schema/1.0/core"')


def _xml(prompt, agent=AGENT, attrs_first=False):
	"""A map carrying one agent task. ``attrs_first`` puts aiSystemPrompt before
	aiAgentConfig, the order an export/import round trip can produce."""
	prompt_attr = f'spiffworkflow:aiSystemPrompt="{frappe.utils.escape_html(prompt)}"'
	config_attr = f'spiffworkflow:aiAgentConfig="{agent}"'
	pair = f"{prompt_attr} {config_attr}" if attrs_first else f"{config_attr} {prompt_attr}"
	return (
		f'<?xml version="1.0"?><bpmn:definitions {NS}>'
		f'<bpmn:process id="p"><bpmn:serviceTask id="orchestrate" {pair} /></bpmn:process>'
		"</bpmn:definitions>"
	)


class TestPromptAlignment(FrappeTestCase):
	def setUp(self):
		if not frappe.db.exists("AI Agent Configuration", AGENT):
			self.skipTest(f"{AGENT} is not on this site")
		self.model = frappe.db.get_value("AI Agent Configuration", AGENT, "process_model")
		if not self.model:
			self.skipTest(f"{AGENT} has no process model on this site")
		self.original_xml = frappe.db.get_value("BPMN Process Model", self.model, "bpmn_xml")
		self.original_prompt = frappe.db.get_value("AI Agent Configuration", AGENT, "system_prompt")

	def tearDown(self):
		frappe.db.rollback()
		super().tearDown()

	def _set(self, xml=None, prompt=None, is_active=1):
		if xml is not None:
			frappe.db.set_value("BPMN Process Model", self.model, "bpmn_xml", xml, update_modified=False)
		frappe.db.set_value("BPMN Process Model", self.model, "is_active", is_active, update_modified=False)
		if prompt is not None:
			frappe.db.set_value("AI Agent Configuration", AGENT, "system_prompt", prompt, update_modified=False)

	def _live_prompt(self):
		return frappe.db.get_value("AI Agent Configuration", AGENT, "system_prompt")

	def test_a_stale_configuration_is_brought_up_to_the_map(self):
		self._set(xml=_xml(MAP_PROMPT), prompt="an older prompt from before the import")
		patch.execute()
		self.assertEqual(self._live_prompt(), MAP_PROMPT)

	def test_an_already_matching_configuration_is_left_alone(self):
		self._set(xml=_xml(MAP_PROMPT), prompt=MAP_PROMPT)
		before = frappe.db.get_value("AI Agent Configuration", AGENT, "modified")
		patch.execute()
		self.assertEqual(self._live_prompt(), MAP_PROMPT)
		self.assertEqual(frappe.db.get_value("AI Agent Configuration", AGENT, "modified"), before)

	def test_a_map_with_no_prompt_changes_nothing(self):
		"""Better to leave a working configuration alone than to blank it because
		the shape happens to carry no aiSystemPrompt."""
		self._set(
			xml=f'<?xml version="1.0"?><bpmn:definitions {NS}><bpmn:process id="p">'
			    f'<bpmn:serviceTask id="orchestrate" spiffworkflow:aiAgentConfig="{AGENT}" />'
			    "</bpmn:process></bpmn:definitions>",
			prompt="the configuration's own prompt",
		)
		patch.execute()
		self.assertEqual(self._live_prompt(), "the configuration's own prompt")

	def test_attribute_order_does_not_matter(self):
		"""An export/import round trip may serialise aiSystemPrompt before
		aiAgentConfig; reading the XML as XML makes the order irrelevant."""
		self._set(xml=_xml(MAP_PROMPT, attrs_first=True), prompt="stale")
		patch.execute()
		self.assertEqual(self._live_prompt(), MAP_PROMPT)

	def test_a_prompt_containing_angle_brackets_survives(self):
		"""A prompt may legitimately contain '>' — a naive tag match would stop
		reading the attributes there and miss the prompt entirely."""
		prompt = "Rules: read > write. Answer in <= 3 lines."
		self._set(xml=_xml(prompt), prompt="stale")
		patch.execute()
		self.assertEqual(self._live_prompt(), prompt)

	def test_a_map_that_is_not_valid_xml_is_left_alone(self):
		self._set(xml="<bpmn:definitions not closed", prompt="the configuration's own prompt")
		patch.execute()
		self.assertEqual(self._live_prompt(), "the configuration's own prompt")

	def test_the_shape_is_found_by_its_agent_not_its_id(self):
		"""A renamed or redrawn agent task must still be matched, so the prompt is
		located by aiAgentConfig rather than by shape id."""
		xml = _xml(MAP_PROMPT).replace('id="orchestrate"', 'id="Activity_renamed_by_someone"')
		self._set(xml=xml, prompt="stale")
		patch.execute()
		self.assertEqual(self._live_prompt(), MAP_PROMPT)

	def test_another_agents_shape_on_the_same_map_is_not_read(self):
		"""A map can carry more than one agent task; only this agent's own counts."""
		xml = (
			f'<?xml version="1.0"?><bpmn:definitions {NS}><bpmn:process id="p">'
			'<bpmn:serviceTask id="theirs" spiffworkflow:aiAgentConfig="Some Other Agent" '
			'spiffworkflow:aiSystemPrompt="theirs, not mine" />'
			f'<bpmn:serviceTask id="mine" spiffworkflow:aiAgentConfig="{AGENT}" '
			'spiffworkflow:aiSystemPrompt="mine, not theirs" />'
			"</bpmn:process></bpmn:definitions>"
		)
		self._set(xml=xml, prompt="stale")
		patch.execute()
		self.assertEqual(self._live_prompt(), "mine, not theirs")

	def test_an_inactive_map_is_not_a_source(self):
		"""Only what the site actually runs may rewrite the prompt."""
		self._set(xml=_xml(MAP_PROMPT), prompt="stale", is_active=0)
		patch.execute()
		self.assertEqual(self._live_prompt(), "stale")
