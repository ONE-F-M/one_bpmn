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
			"onefm.created_config",
			"onefm.script_diff",
			"onefm.test_cases",
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

	def test_verified_creation_becomes_created_config(self):
		reply = {
			"message": "Created Leave Summarizer",
			"created_config": {"name": "Leave Summarizer", "agent_id": "leave_summarizer"},
		}
		events = _named(translators._assistant_created(reply))
		value = events["onefm.created_config"]
		self.assertEqual(value["name"], "Leave Summarizer")
		self.assertEqual(value["summary"], "Created Leave Summarizer")
		self.assertEqual(agui_contract.validate_event("onefm.created_config", value), [])

	def test_created_config_without_name_produces_nothing(self):
		# The shaper only sets created_config after verifying the record, but
		# the translator still refuses a nameless dict — no event, no linking.
		self.assertEqual(list(translators._assistant_created({"created_config": {}})), [])

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
			translators._assistant_created,
			translators._table,
			translators._typed_artifact,
		):
			self.assertEqual(list(fn(reply)), [], fn.__name__)


class TestTypedArtifact(FrappeTestCase):
	"""The generic `artifact` reply key renders through the typed event the
	agent's Artifact Type names (WI-001996, wired)."""

	def test_script_artifact_becomes_script_diff(self):
		reply = {
			"response": "Here you go",
			"artifact": "def x():\n    return 1",
			"artifact_type": "Script",
		}
		events = _named(translators._typed_artifact(reply))
		value = events["onefm.script_diff"]
		self.assertEqual(value["mode"], "CREATE")
		self.assertEqual(value["modified_script"], "def x():\n    return 1")
		self.assertEqual(agui_contract.validate_event("onefm.script_diff", value), [])

	def test_wrapped_script_artifact_carries_name_and_mode(self):
		reply = {
			"artifact": {"content": "def x(): ...", "name": "Dept Rollup", "mode": "MODIFY"},
			"artifact_type": "Script",
		}
		value = _named(translators._typed_artifact(reply))["onefm.script_diff"]
		self.assertEqual(value["mode"], "MODIFY")
		self.assertEqual(value["suggested_name"], "Dept Rollup")

	def test_diagram_artifact_becomes_bpmn_preview(self):
		reply = {"artifact": "<bpmn:definitions/>", "artifact_type": "Diagram", "response": "drawn"}
		value = _named(translators._typed_artifact(reply))["onefm.bpmn_preview"]
		self.assertEqual(value["mode"], "generated")
		self.assertEqual(agui_contract.validate_event("onefm.bpmn_preview", value), [])

	def test_schema_artifact_becomes_doctype_schema(self):
		reply = {"artifact": {"name": "X", "fields": []}, "artifact_type": "Schema"}
		value = _named(translators._typed_artifact(reply))["onefm.doctype_schema"]
		self.assertEqual(value["doctype_ir"], {"name": "X", "fields": []})
		self.assertEqual(agui_contract.validate_event("onefm.doctype_schema", value), [])

	def test_record_artifact_becomes_proposed_update(self):
		reply = {"artifact": {"status": "Approved"}, "artifact_type": "Record"}
		value = _named(translators._typed_artifact(reply))["onefm.proposed_update"]
		self.assertEqual(value["fields"], {"status": "Approved"})
		self.assertEqual(agui_contract.validate_event("onefm.proposed_update", value), [])

	def test_no_or_none_artifact_type_stands_down(self):
		self.assertEqual(list(translators._typed_artifact({"artifact": "code"})), [])
		self.assertEqual(
			list(translators._typed_artifact({"artifact": "code", "artifact_type": "None"})), []
		)

	def test_bespoke_reply_keys_win(self):
		# A reply its own translator already handles never double-renders.
		reply = {
			"artifact": "def x(): ...",
			"artifact_type": "Script",
			"modified_script": "def x(): ...",
			"intent": "CREATE",
		}
		self.assertEqual(list(translators._typed_artifact(reply)), [])


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

	def test_stream_resolves_artifact_type_from_the_agent_config(self):
		import json
		from unittest.mock import patch

		from one_bpmn.agents import agui_stream

		# A generic agent: no bespoke keys, just `artifact` — the stream must
		# stamp artifact_type from the configuration and emit the typed event.
		reply = {"response": "wrote it", "artifact": "def y(): ...", "conversation": "CONV-2"}
		with (
			patch("one_bpmn.api.agent_invocation.invoke_agent", return_value=reply),
			patch.object(agui_stream, "_agent_artifact_type", return_value="Script"),
		):
			chunks = list(agui_stream.agent_event_stream("generic", "m", "CONV-2"))
		customs = []
		for chunk in chunks:
			for line in chunk.splitlines():
				if line.startswith("data: "):
					e = json.loads(line[6:])
					if e.get("type") == "CUSTOM":
						customs.append(e)
		names = [c["name"] for c in customs]
		self.assertIn("onefm.script_diff", names)
		value = next(c["value"] for c in customs if c["name"] == "onefm.script_diff")
		self.assertEqual(value["modified_script"], "def y(): ...")
		self.assertEqual(agui_contract.validate_event("onefm.script_diff", value), [])
