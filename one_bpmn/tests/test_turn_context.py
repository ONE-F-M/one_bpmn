# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""The platform's history step, and the two things it replaces.

Six agents each rebuilt this in their own Build Context script and five of them
never called build_history, so five never saw a compaction summary. The point of
these tests is the properties that were previously true of one agent and now
have to be true of all of them.
"""

from types import SimpleNamespace
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.agents.context_assembler import build_dynamic_preamble
from one_bpmn.agents.memory.session_state import LAST_TURN_KEY, get_state, record, record_turn_result
from one_bpmn.agents.memory.turn_context import (
	ESTABLISHED_HEADER,
	FACT_MAX_CHARS,
	conversation_of,
	established_block,
	established_facts,
	load_history,
)
from one_bpmn.tests.conversation_fixtures import drop_conversations
from one_bpmn.utils.chat_persistence import create_conversation, save_bot_message, save_user_message


class TurnContextCase(FrappeTestCase):
	def setUp(self):
		self.made = []

	def tearDown(self):
		drop_conversations(self.made)

	def _conversation(self, turns=0, mode="Turn context test"):
		# A new conversation or message is a doc event every live map may start on.
		with patch("frappe.enqueue"), patch("one_bpmn.one_bpmn.trigger.on_doc_event"):
			name = create_conversation(
				agent_mode=mode, title=f"Turn ctx {frappe.generate_hash(length=8)}",
				user="Administrator",
			)
			self.made.append(name)
			for i in range(turns):
				save_user_message(name, f"question {i}")
				save_bot_message(name, f"answer {i}")
		frappe.db.commit()
		return name


class TestWhichConversation(TurnContextCase):
	def test_a_chat_turn_resolves_its_conversation(self):
		inst = SimpleNamespace(context_doctype="Chat Conversation", context_docname="conv-1")
		self.assertEqual(conversation_of(inst), "conv-1")

	def test_a_background_agent_has_none(self):
		"""A Background agent's prompt is not a chat turn, priming it with a
		transcript would be inventing history it never had."""
		inst = SimpleNamespace(context_doctype="A2A Task", context_docname="A2A-1")
		self.assertEqual(conversation_of(inst), "")

	def test_a_conversationless_instance_has_none(self):
		self.assertEqual(conversation_of(SimpleNamespace()), "")


class TestHistory(TurnContextCase):
	def test_it_returns_the_recent_turns_as_messages(self):
		conv = self._conversation(turns=3)
		history = load_history(conv, limit=20)
		self.assertTrue(history)
		self.assertTrue(all({"role", "content"} <= set(m) for m in history))
		self.assertIn("answer 2", history[-1]["content"])

	def test_the_window_is_what_the_agent_asked_for(self):
		"""aiContextMaxMessages was overlaid onto the shape and read by nothing.
		Changing it must change the prompt, which is the whole acceptance test."""
		conv = self._conversation(turns=8)
		self.assertLessEqual(len(load_history(conv, limit=4)), 4)
		self.assertGreater(len(load_history(conv, limit=12)), 4)

	def test_no_window_falls_back_rather_than_sending_nothing(self):
		conv = self._conversation(turns=3)
		self.assertTrue(load_history(conv, limit=0))

	def test_markup_is_stripped_for_everyone(self):
		"""Three agents carry their own stripper, each claiming Bleach linkifies
		URLs before they reach Chat Message. It does not, none of this site's
		5,231 messages holds an anchor, but 66 do hold some tag, and a tag in
		the transcript is noise the model pays for. Stripped once, here."""
		conv = self._conversation()
		with patch("frappe.enqueue"):
			save_user_message(conv, 'see <a href="https://lucid.app/x">https://lucid.app/x</a>')
		frappe.db.commit()
		text = " ".join(m["content"] for m in load_history(conv, limit=5))
		self.assertNotIn("<a href", text)
		self.assertIn("lucid.app/x", text)

	def test_this_turns_own_question_is_not_replayed_as_history(self):
		"""Every chat map saves the user message as its FIRST step, so by the
		time the AI task dispatches the question is already stored. Without this
		the model reads it twice, once as the newest history entry and once from
		the preamble's "User message:" line, and treats them as two turns."""
		conv = self._conversation(turns=2)
		with patch("frappe.enqueue"):
			save_user_message(conv, "what changed in the schema?")
		frappe.db.commit()

		with_dup = load_history(conv, limit=20)
		self.assertEqual(with_dup[-1]["content"].strip(), "what changed in the schema?")

		clean = load_history(conv, limit=20, current_message="what changed in the schema?")
		self.assertEqual(len(clean), len(with_dup) - 1)
		self.assertNotEqual(clean[-1]["content"].strip(), "what changed in the schema?")

	def test_the_same_question_asked_earlier_stays_in_history(self):
		"""Only the trailing entry is this turn's. An identical question asked
		three turns ago is genuine history and dropping it would lose a turn."""
		conv = self._conversation()
		with patch("frappe.enqueue"):
			save_user_message(conv, "run it again")
			save_bot_message(conv, "done")
			save_user_message(conv, "run it again")
		frappe.db.commit()
		clean = load_history(conv, limit=20, current_message="run it again")
		self.assertEqual(sum(1 for m in clean if m["content"].strip() == "run it again"), 1)

	def test_a_trailing_assistant_message_is_never_dropped(self):
		conv = self._conversation(turns=2)
		clean = load_history(conv, limit=20, current_message="answer 1")
		self.assertEqual(clean[-1]["content"].strip(), "answer 1")

	def test_an_unknown_conversation_is_empty_not_an_error(self):
		self.assertEqual(load_history("no-such-conversation", limit=5), [])

	def test_history_never_takes_the_turn_down(self):
		"""An agent that cannot read its past must still answer the present."""
		conv = self._conversation(turns=2)
		with patch("one_bpmn.agents.memory.compaction.build_history",
		           side_effect=RuntimeError("reader exploded")):
			self.assertEqual(load_history(conv, limit=5), [])


class TestEstablishedFacts(TurnContextCase):
	def test_recorded_facts_come_back_under_the_header(self):
		conv = self._conversation()
		record(conv, {"process_name": "Onboarding", "confirmed_action": "create"})
		block = established_block(conv)
		self.assertIn(ESTABLISHED_HEADER, block)
		self.assertIn("Onboarding", block)

	def test_nothing_established_sends_no_block_at_all(self):
		"""ProsAlly sent the header with an empty body every single turn, because
		it read session_state that nothing in ProsAlly ever wrote."""
		self.assertEqual(established_block(self._conversation()), "")

	def test_an_unknown_conversation_is_empty(self):
		self.assertEqual(established_block("no-such-conversation"), "")


	def test_working_material_stays_out_of_the_block(self):
		"""LuCrusher parks a parsed Lucidchart document and its whole migration
		snapshot in session state; neither is a fact to restate every turn."""
		name = self._conversation()
		record(name, {
			"intent": "TOPOLOGY_DRAFT",
			"lucid_doc:abc": {"summary": "x" * 5000, "pages": [{"title": "p1"}]},
			"topology": {"processes": [{"process_name": "Onboarding"}]},
			"matches": ["Onboarding", "Offboarding"],
			"_scratch": "hidden",
			"essay": "y" * (FACT_MAX_CHARS + 1),
		})
		block = established_block(name)
		self.assertIn('"intent": "TOPOLOGY_DRAFT"', block)
		self.assertIn('"Offboarding"', block)
		self.assertNotIn("lucid_doc", block)
		self.assertNotIn("topology", block)
		self.assertNotIn("_scratch", block)
		self.assertNotIn("essay", block)
		self.assertLess(len(block), 400)

	def test_facts_are_scalars_and_short_lists_only(self):
		state = {"a": 1, "b": "two", "c": [1, 2], "d": {"k": 1}, "e": [{"k": 1}], "f": "", "g": None, "h": True}
		self.assertEqual(established_facts(state), {"a": 1, "b": "two", "c": [1, 2], "h": True})


class TestRecordTurnResult(TurnContextCase):
	def test_the_named_keys_and_facts_land_with_a_one_line_summary(self):
		name = self._conversation()
		output = {
			"intent": "PROPOSE",
			"response": "Here is the form.",
			"options": [],
			"suggested_name": "Site Visit",
			"doctype_ir": {"fields": [{"fieldname": "site"}]},
			"diff": None,
		}
		record_turn_result(name, output, keys=("suggested_name", "diff"), target_module="HR", doctype="")
		state = get_state(name)
		self.assertEqual(state["suggested_name"], "Site Visit")
		self.assertEqual(state["target_module"], "HR")
		self.assertNotIn("doctype", state)
		self.assertNotIn("diff", state)
		self.assertNotIn("doctype_ir", state)
		self.assertEqual(state[LAST_TURN_KEY], "PROPOSE (produced: doctype_ir, suggested_name)")
		self.assertIn("PROPOSE (produced: doctype_ir, suggested_name)", established_block(name))

	def test_a_turn_without_structured_output_records_only_its_facts(self):
		name = self._conversation()
		record_turn_result(name, None, process_name="Onboarding")
		self.assertEqual(get_state(name), {"process_name": "Onboarding"})

	def test_nothing_to_record_writes_nothing(self):
		name = self._conversation()
		record_turn_result(name, {}, keys=("missing",), process_name="")
		self.assertEqual(get_state(name), {})


class TestPlatformHistoryStep(TurnContextCase):
	def test_a_chat_turn_gets_its_window_and_the_turn_store_gets_the_same(self):
		from one_bpmn.agents.turn_state import clear_turn, get_turn
		from one_bpmn.one_bpmn.doctype.bpmn_process_instance.dispatchers import _platform_history

		name = self._conversation(turns=3)
		with patch("frappe.enqueue"), patch("one_bpmn.one_bpmn.trigger.on_doc_event"):
			save_user_message(name, "question 3")
		record(name, {"process_name": "Onboarding"})
		instance = SimpleNamespace(context_doctype="Chat Conversation", context_docname=name)
		try:
			history, facts = _platform_history(instance, {"aiContextMaxMessages": "4"}, "question 3")
			# A window of 4 over 7 stored messages, minus this turn's own question.
			self.assertEqual([m["content"] for m in history], ["answer 1", "question 2", "answer 2"])
			self.assertIn('"process_name": "Onboarding"', facts)
			self.assertEqual(get_turn(name).get("chat_history"), history)
		finally:
			clear_turn(name)

	def test_anything_but_a_chat_turn_gets_nothing(self):
		from one_bpmn.one_bpmn.doctype.bpmn_process_instance.dispatchers import _platform_history

		instance = SimpleNamespace(context_doctype="Work Item", context_docname="WI-1")
		self.assertEqual(_platform_history(instance, {}, ""), ([], ""))


class TestCurrentMessageMarkup(FrappeTestCase):
	def test_the_persons_words_reach_the_model_without_markup(self):
		from one_bpmn.one_bpmn.doctype.bpmn_process_instance.dispatchers import _turn_user_message

		instance = SimpleNamespace(context_doctype="Chat Conversation", context_docname="conv-1")
		task = SimpleNamespace(data={"user_text": '<p>crush <a href="https://lucid.app/x">https://lucid.app/x</a>&nbsp;now</p>'})
		self.assertEqual(_turn_user_message(instance, task), "crush https://lucid.app/x now")


class TestPreamblePlacement(FrappeTestCase):
	def test_the_established_block_sits_in_the_cacheable_prefix(self):
		"""Before the marker, with memory and instructions, it changes only when
		a turn establishes something, unlike the person's words."""
		out = build_dynamic_preamble(
			memory_block="MEM", instructions="DO THIS",
			user_prompt="hello", established_block="FACTS",
		)
		self.assertLess(out.index("FACTS"), out.index("User message:"))
		self.assertLess(out.index("MEM"), out.index("FACTS"))

	def test_it_is_absent_when_nothing_is_established(self):
		self.assertEqual(
			build_dynamic_preamble(user_prompt="hello", established_block=""),
			build_dynamic_preamble(user_prompt="hello"),
		)

	def test_an_agent_with_only_facts_still_gets_them(self):
		out = build_dynamic_preamble(user_prompt="hello", established_block="FACTS")
		self.assertIn("FACTS", out)
		self.assertIn("hello", out)


class TestNoMapAlsoSendsHistory(FrappeTestCase):
	"""The platform sends the transcript as real messages, so a map that also
	flattens it into its prompt sends every prior turn twice, which is worse
	than the duplication this work set out to remove.

	LuCrusher did exactly that: its prompt rendered {{ history_block }} while
	its Build Context script filled it with "Conversation so far:". Caught only
	by reading the maps, so this reads them on every run.
	"""

	def _active_chat_maps(self):
		import re

		out = []
		for cfg in frappe.get_all(
			"AI Agent Configuration",
			filters={"enabled": 1, "agent_type": "Chat"},
			fields=["name", "process_model"],
		):
			if not cfg.process_model:
				continue
			xml = frappe.db.get_value("BPMN Process Model", cfg.process_model, "bpmn_xml") or ""
			if not xml:
				continue
			for prompt in re.findall(r'spiffworkflow:aiUserPrompt="(.*?)"\s+spiffworkflow:', xml, re.S):
				out.append((cfg.name, cfg.process_model, prompt))
		return out

	def test_no_live_chat_prompt_renders_a_transcript(self):
		import html as _html

		offenders = []
		for agent, model, prompt in self._active_chat_maps():
			text = _html.unescape(prompt)
			if "chat_history" in text or "Conversation so far" in text:
				offenders.append(f"{agent} ({model})")
		self.assertEqual(
			offenders, [],
			"these maps flatten history into the prompt while the platform also "
			"sends it as messages, so the model reads every turn twice: "
			+ ", ".join(offenders),
		)

	def test_no_build_context_script_fills_a_history_block(self):
		"""The other half of the same mistake, the prompt placeholder is
		harmless while the script leaves it empty."""
		offenders = []
		for s in frappe.get_all("Server Script", filters={"name": ["like", "%Build Context%"]},
		                        pluck="name"):
			body = frappe.db.get_value("Server Script", s, "script") or ""
			if "Conversation so far" in body:
				offenders.append(s)
		self.assertEqual(offenders, [], "still building a transcript block: " + ", ".join(offenders))


class TestToolCallingTurnSendsHistory(FrappeTestCase):
	"""Every chat agent calls tools, so the tool loop is where history has to reach the model."""

	def test_prior_turns_precede_the_message_in_the_first_model_call(self):
		from one_bpmn.agents.executor import ExecutorConfig
		from one_bpmn.agents.executor.direct_api import DirectApiExecutor
		from one_bpmn.agents.llm_provider.base import StepResult, ToolSpec

		seen = []

		class RecordingAdapter:
			async def step(self, system, transcript, tools=None, max_tokens=16384):
				seen.append(list(transcript))
				return StepResult(content="Falcon")

		history = [
			{"role": "user", "content": "My project is Project Falcon."},
			{"role": "assistant", "content": "Noted."},
		]
		config = ExecutorConfig(
			model="m",
			system_prompt="s",
			user_prompt="What is my project called?",
			messages=history,
			tools=[ToolSpec(fn=lambda **kw: "ok", name="lookup", description="a read")],
		)
		with patch(
			"one_bpmn.agents.llm_provider.factory.get_llm_adapter", return_value=RecordingAdapter()
		):
			DirectApiExecutor()._run_with_tools(config, "Anthropic", "key", "m")

		self.assertEqual(
			seen[0], [*history, {"role": "user", "content": "What is my project called?"}]
		)
