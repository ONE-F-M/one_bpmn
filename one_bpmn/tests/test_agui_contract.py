# Copyright (c) 2026, one-fm and contributors
# WI-001671: the onefm.* extension event contract and its translators.

from __future__ import annotations

from frappe.tests.utils import FrappeTestCase

from one_bpmn.agents import agui_contract
from one_bpmn.agents.agui_contract import translators


def _named(events):
	return {e.name: e.value for e in events}


class TestContractData(FrappeTestCase):
	def test_every_example_validates_against_its_own_schema(self):
		problems = agui_contract.validate_examples()
		self.assertEqual(problems, [], f"contract examples are invalid: {problems}")

	def test_expected_event_inventory(self):
		expected = {
			"onefm.choice",
			"onefm.proposed_config",
			"onefm.proposed_update",
			"onefm.script_diff",
			"onefm.bpmn_preview",
			"onefm.doctype_schema",
			"onefm.table",
			"onefm.conversation_title",
			"onefm.mode_transition",
			"onefm.lucrusher_result",
		}
		self.assertEqual(set(agui_contract.list_events()), expected)

	def test_unknown_namespaced_event_is_a_violation(self):
		problems = agui_contract.validate_event("onefm.made_up", {"x": 1})
		self.assertTrue(problems and "unknown contract event" in problems[0])

	def test_non_namespaced_event_is_a_violation(self):
		problems = agui_contract.validate_event("MODE_TRANSITION", {"new_mode": "x"})
		self.assertTrue(problems and "namespace" in problems[0])

	def test_schema_rejects_bad_payload(self):
		problems = agui_contract.validate_event("onefm.choice", {"prompt": "pick"})  # no options
		self.assertTrue(problems)


class TestTranslators(FrappeTestCase):
	"""Legacy reply dicts (shapes verified on staging) → contract events."""

	def test_logix_modify_becomes_script_diff(self):
		reply = {
			"intent": "MODIFY",
			"response": "Here's the change",
			"modified_script": "def x(): ...",
			"diff": [{"type": "added", "right": "def x(): ..."}],
			"suggested_name": "Dept Rollup",
		}
		events = _named(translators._script_diff(reply))
		self.assertIn("onefm.script_diff", events)
		value = events["onefm.script_diff"]
		self.assertEqual(value["mode"], "MODIFY")
		self.assertEqual(agui_contract.validate_event("onefm.script_diff", value), [])

	def test_prosally_generated_becomes_bpmn_preview(self):
		reply = {"intent": "BPMN_GENERATED", "bpmn_xml": "<bpmn/>", "response": "done"}
		events = _named(translators._bpmn_preview(reply))
		value = events["onefm.bpmn_preview"]
		self.assertEqual(value["mode"], "generated")
		self.assertEqual(agui_contract.validate_event("onefm.bpmn_preview", value), [])

	def test_prosally_removal_gate_is_a_preview_not_choice_buttons(self):
		from one_bpmn.agents.agui_stream import _choice_translator

		reply = {
			"intent": "CONFIRM_REMOVAL",
			"pending_xml": "<bpmn/>",
			"options": ["Yes, apply changes", "No, keep it"],
			"response": "This removes the auto-approve path.",
		}
		preview = _named(translators._bpmn_preview(reply))
		self.assertEqual(preview["onefm.bpmn_preview"]["mode"], "pending_removal")
		# and the generic choice translator stands down for this payload
		self.assertEqual(list(_choice_translator(reply)), [])

	def test_docu_ir_becomes_doctype_schema(self):
		reply = {"doctype_ir": {"name": "X", "fields": []}, "exists": 1, "custom": 1}
		events = _named(translators._doctype_schema(reply))
		value = events["onefm.doctype_schema"]
		self.assertTrue(value["exists"] and value["custom"])
		self.assertEqual(agui_contract.validate_event("onefm.doctype_schema", value), [])

	def test_assistant_proposal_and_recommendations(self):
		reply = {
			"message": "Here you go",
			"proposal": {"agent_name": "Leave Summarizer"},
			"recommendations": {"model": "claude-haiku-4-5-20251001"},
		}
		events = _named(translators._assistant_proposals(reply))
		self.assertIn("onefm.proposed_config", events)
		self.assertIn("onefm.proposed_update", events)
		for name, value in events.items():
			self.assertEqual(agui_contract.validate_event(name, value), [], name)

	def test_table_key_becomes_onefm_table(self):
		reply = {
			"response": "here",
			"table": {
				"columns": [{"key": "a", "label": "A"}],
				"rows": [{"a": 1}],
			},
		}
		events = _named(translators._table(reply))
		self.assertEqual(agui_contract.validate_event("onefm.table", events["onefm.table"]), [])

	def test_plain_reply_produces_nothing(self):
		reply = {"response": "just words"}
		for fn in (
			translators._script_diff,
			translators._bpmn_preview,
			translators._doctype_schema,
			translators._assistant_proposals,
			translators._table,
		):
			self.assertEqual(list(fn(reply)), [], fn.__name__)


class TestEndToEndTranslation(FrappeTestCase):
	"""The shared stream emits validated contract events for legacy dicts."""

	def test_stream_carries_script_diff_custom_event(self):
		import json
		from unittest.mock import patch

		from one_bpmn.agents import agui_stream

		reply = {
			"response": "I can update Dept Rollup",
			"intent": "MODIFY",
			"modified_script": "def x(): ...",
			"conversation": "CONV-1",
		}
		with patch("one_bpmn.api.agent_invocation.invoke_agent", return_value=reply):
			chunks = list(agui_stream.agent_event_stream("logix", "m", "CONV-1"))
		customs = []
		for chunk in chunks:
			for line in chunk.splitlines():
				if line.startswith("data: "):
					e = json.loads(line[6:])
					if e.get("type") == "CUSTOM":
						customs.append(e)
		names = [c["name"] for c in customs]
		self.assertIn("onefm.script_diff", names)
		for c in customs:
			self.assertEqual(agui_contract.validate_event(c["name"], c["value"]), [], c["name"])
