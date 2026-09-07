# Copyright (c) 2026, one-fm and contributors
# WI-001680: cross-agent AG-UI conformance.
#
# One turn through every agent — the five system agents plus one
# pure-configuration agent (no dedicated code anywhere) — validated as a
# proper AG-UI event stream by the shared validator in agui_contract.
# Uniformity is enforced by CI, not remembered by people: if an agent
# answers in its own dialect again, the build fails naming the agent and
# the offending event.
#
# No live LLM: system agents run against recorded reply shapes at the
# runner boundary (the real stream, translators and shapers all execute);
# the pure-config agent runs the REAL direct_api path end to end — real
# configuration row, real conversation and Chat Message persistence — with
# only the model adapter mocked.

from __future__ import annotations

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.agents import agui_contract


def _run_recorded(agent_id: str, reply, runner_key: str = "bpmn_map") -> list:
	"""Drive one real agent_event_stream turn with a recorded runner reply.

	Everything above the runner is live: the stream lifecycle, the reply
	shapers, the contract translators, the relay rules.
	"""
	from one_bpmn.agents import agui_stream
	from one_bpmn.api import agent_invocation as ai

	class _Screened:
		text = "msg"
		enabled = False

	def runner(config, conversation, message, context, stream=False):
		if callable(reply):
			return reply(stream)
		return reply

	patches = [
		patch.object(ai, "_resolve_config", return_value={"agent_id": agent_id, "name": agent_id}),
		patch.object(ai, "_authorize"),
		patch.object(ai, "_runner_for", return_value=runner_key),
		patch.dict(ai._RUNNERS, {runner_key: runner}),
		patch("one_bpmn.security.pii.screen_input", return_value=_Screened()),
		patch("one_bpmn.security.pii.begin_turn", return_value=object()),
		patch("one_bpmn.security.pii.end_turn"),
	]
	for p in patches:
		p.start()
	try:
		return list(agui_stream.agent_event_stream(agent_id, "one turn", "CONV-CONF"))
	finally:
		for p in patches:
			p.stop()


class TestCrossAgentConformance(FrappeTestCase):
	"""One recorded turn per system agent, validated by the shared rules."""

	def assertConformant(self, chunks, agent_id):
		problems = agui_contract.validate_stream(chunks, agent_id=agent_id)
		self.assertEqual(problems, [], f"{agent_id} is not conformant: {problems}")

	def test_ai_assistant_turn(self):
		# The assistant's map answers in its JSON text contract; the shaper
		# must lift it so no raw JSON reaches the text events.
		raw = (
			'{"message": "Here is my suggestion.", '
			'"recommendations": {"aiModel": "claude-haiku-4-5-20251001"}}'
		)
		chunks = _run_recorded("ai_agent_assistant", {"response": raw, "conversation": "CONV-CONF"})
		self.assertConformant(chunks, "ai_agent_assistant")
		joined = "".join(chunks)
		self.assertNotIn('\\"recommendations\\"', joined.split("CUSTOM")[0], "raw JSON leaked into text")

	def test_logix_turn(self):
		reply = {
			"response": "I can update Dept Rollup",
			"intent": "MODIFY",
			"modified_script": "def get_department(employee):\n    return employee.department",
			"suggested_name": "Dept Rollup",
			"conversation": "CONV-CONF",
		}
		chunks = _run_recorded("logix_agent", reply)
		self.assertConformant(chunks, "logix_agent")
		self.assertIn("onefm.script_diff", "".join(chunks))

	def test_prosally_turn_including_removal_gate(self):
		reply = {
			"response": "This removes the auto-approve path.",
			"intent": "CONFIRM_REMOVAL",
			"pending_xml": "<bpmn:definitions/>",
			"options": ["Yes, apply changes", "No, keep it"],
			"conversation": "CONV-CONF",
		}
		chunks = _run_recorded("prosally_agent", reply)
		self.assertConformant(chunks, "prosally_agent")
		joined = "".join(chunks)
		self.assertIn("onefm.bpmn_preview", joined)
		self.assertIn("pending_removal", joined)
		self.assertNotIn("onefm.choice", joined, "removal gate must be the card, not loose buttons")

	def test_docu_turn(self):
		reply = {
			"response": "Added an emergency contact section.",
			"doctype_ir": {"name": "Employee Onboarding", "fields": [{"fieldname": "contact_name", "fieldtype": "Data"}]},
			"exists": True,
			"custom": True,
			"conversation": "CONV-CONF",
		}
		chunks = _run_recorded("docu_agent", reply)
		self.assertConformant(chunks, "docu_agent")
		self.assertIn("onefm.doctype_schema", "".join(chunks))

	def test_lumina_streaming_turn_with_legacy_custom_names(self):
		# The langgraph/Lumina path streams; legacy CUSTOM names must adopt
		# their contract names at the relay boundary.
		def reply(stream):
			def child():
				# The producers' REAL shape: `event` rather than `name`, with
				# the payload flat on the event (lumina.py). The double used
				# to speak the contract already, which hid the missing fold
				# for three weeks (WI-001678).
				yield {"type": "RUN_STARTED", "run_id": "child"}
				yield {"type": "TEXT_MESSAGE_CONTENT", "delta": "token "}
				yield {"type": "CUSTOM", "event": "MODE_TRANSITION", "new_mode": "Planning"}
				yield {"type": "CUSTOM", "event": "HEARTBEAT"}
				yield {"type": "RUN_FINISHED", "run_id": "child"}
			return child()

		chunks = _run_recorded("lumina_general_chat", reply, runner_key="langgraph")
		self.assertConformant(chunks, "lumina_general_chat")
		joined = "".join(chunks)
		self.assertIn("onefm.mode_transition", joined)
		self.assertNotIn("MODE_TRANSITION", joined.replace("onefm.mode_transition", ""))
		self.assertNotIn("HEARTBEAT", joined, "keep-alives are transport, never events")
		self.assertIn('"new_mode": "Planning"', joined, "the payload must reach the client under value")


class TestPureConfigurationAgent(FrappeTestCase):
	"""The zero-code path, end to end: a chat agent that exists ONLY as an
	AI Agent Configuration row — real conversation, real persistence, real
	direct_api runner; only the model adapter is mocked."""

	AGENT_ID = "conformance_dummy_agent"

	def _ensure_config(self):
		if frappe.db.exists("AI Agent Configuration", {"agent_id": self.AGENT_ID}):
			return
		frappe.get_doc(
			{
				"doctype": "AI Agent Configuration",
				"agent_name": "Conformance Dummy",
				"agent_id": self.AGENT_ID,
				"agent_framework": "Direct API",
				"agent_type": "Chat",
				"enabled": 1,
				"lifecycle_status": "Live",
				"chat_mode_label": "Conformance Dummy",
				"system_prompt": "You are a test agent.",
			}
		).insert(ignore_permissions=True)

	def test_config_only_agent_is_conformant(self):
		self._ensure_config()

		from one_bpmn.agents import agui_stream
		from one_bpmn.utils.chat_persistence import create_agent_conversation

		conversation = create_agent_conversation(self.AGENT_ID, title="conformance", user=frappe.session.user)

		class _Completion:
			text = "A perfectly ordinary answer."

		class _Adapter:
			async def complete(self, system="", user=""):
				return _Completion()

		with patch(
			"one_bpmn.agents.llm_provider.get_llm_adapter_from_settings", return_value=_Adapter()
		):
			chunks = list(
				agui_stream.agent_event_stream(self.AGENT_ID, "hello there", conversation)
			)

		problems = agui_contract.validate_stream(chunks, agent_id=self.AGENT_ID)
		self.assertEqual(problems, [], problems)
		self.assertIn("A perfectly ordinary answer.", "".join(chunks))
		# the turn really persisted — the zero-code agent is a full citizen
		count = frappe.db.count("Chat Message", {"conversation": conversation})
		self.assertGreaterEqual(count, 2, "user + bot messages should persist")


class TestValidatorNamesTheViolator(FrappeTestCase):
	"""A failure must say WHO and WHAT — that is the whole point of CI."""

	def test_rogue_dialect_fails_naming_agent_and_event(self):
		reply = {
			"response": "here",
			"table": {"columns": [{"key": "a"}], "rows": []},  # column missing required label
			"conversation": "CONV-CONF",
		}
		chunks = _run_recorded("rogue_agent", reply)
		problems = agui_contract.validate_stream(chunks, agent_id="rogue_agent")
		self.assertTrue(problems, "an invalid onefm.table payload must fail conformance")
		self.assertTrue(any("rogue_agent" in p and "onefm.table" in p for p in problems), problems)

	def test_unknown_custom_name_fails(self):
		problems = agui_contract.validate_event("onefm.i_made_this_up", {})
		self.assertTrue(problems and "unknown contract event" in problems[0])
