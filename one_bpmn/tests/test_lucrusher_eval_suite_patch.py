# Copyright (c) 2026, one-fm and contributors

import json
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.one_bpmn.patches.v1_0 import repoint_lucrusher_judge_model as repoint
from one_bpmn.one_bpmn.patches.v1_0 import seed_lucrusher_eval_suite as seed


class TestLucrusherEvalSuitePatch(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		if frappe.db.exists("AI Agent Configuration", {"agent_id": seed.AGENT_ID}):
			return
		model = frappe.get_doc(
			{"doctype": "BPMN Process Model", "title": "zz-lucrusher-stub-map", "process_id": "zz_lucrusher_stub", "version": 1}
		)
		model.flags.skip_editability_check = True
		model.flags.skip_script_security_check = True
		model.insert(ignore_permissions=True)
		frappe.get_doc(
			{
				"doctype": "AI Agent Configuration",
				"agent_name": "ZZ LuCrusher Stub",
				"agent_id": seed.AGENT_ID,
				"agent_type": "Background",
				"agent_framework": "Direct API",
				"process_model": model.name,
			}
		).insert(ignore_permissions=True)

	def _cases(self):
		suite = frappe.db.get_value("AI Eval Suite", {"title": seed.SUITE_TITLE})
		return {c.title: frappe.get_doc("AI Eval Case", c.name) for c in frappe.get_all("AI Eval Case", {"suite": suite}, ["name", "title"])}

	def test_seeding_twice_leaves_one_suite_and_six_cases(self):
		seed.execute()
		seed.execute()
		self.assertEqual(frappe.db.count("AI Eval Suite", {"title": seed.SUITE_TITLE}), 1)
		self.assertEqual(len(self._cases()), 6)

	def test_every_case_checks_the_finalize_intent(self):
		seed.execute()
		for title, case in self._cases().items():
			finalize = [row for row in case.expected_tool_calls if row.tool_name == "finalize"]
			self.assertEqual(len(finalize), 1, title)
			self.assertEqual(finalize[0].argument, "intent", title)
			self.assertIn("tool_calls", [a.assertion_type for a in case.assertions], title)

	def test_the_follow_up_cases_start_from_earlier_turns(self):
		seed.execute()
		cases = self._cases()
		for title in (
			"The same Lucidchart link again uses the fetched copy",
			"A codebase scan after the document is fetched",
			"Confirming the proposed topology",
		):
			context = json.loads(cases[title].input_context)
			types = [m["message_type"] for m in context["conversation_messages"]]
			self.assertEqual(types, ["User", "Bot", "Tool"], title)
			self.assertIn(f"lucid_doc:{seed.LUCID_DOC_ID}", context["session_state"], title)

	def test_the_suite_does_not_block_deploys_before_its_first_run(self):
		seed.execute()
		suite = frappe.get_doc("AI Eval Suite", {"title": seed.SUITE_TITLE})
		self.assertEqual(suite.gate_deployment, 0)
		self.assertEqual((suite.pass_k, suite.min_pass_rate), (seed.PASS_K, seed.MIN_PASS_RATE))

	def test_a_site_without_lucrusher_is_left_alone(self):
		frappe.db.delete("AI Eval Suite", {"title": seed.SUITE_TITLE})
		with patch.object(seed, "AGENT_ID", "zz_no_such_agent"):
			seed.execute()
		self.assertFalse(frappe.db.exists("AI Eval Suite", {"title": seed.SUITE_TITLE}))


class TestLucrusherJudgeModel(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self.provider = "zz-judge-provider"
		if not frappe.db.exists("AI Provider", self.provider):
			frappe.get_doc({"doctype": "AI Provider", "provider": self.provider}).insert(
				ignore_permissions=True
			)
		for name, enabled in (("zz-judge-off", 0), ("zz-judge-on", 1)):
			if not frappe.db.exists("AI Model", name):
				frappe.get_doc(
					{
						"doctype": "AI Model",
						"model_name": name,
						"provider": self.provider,
						"enable_model": enabled,
						"api_key": "zz-test-key",
					}
				).insert(ignore_permissions=True)
		suffix = frappe.generate_hash(length=6)
		self.agent = frappe.get_doc(
			{
				"doctype": "AI Agent Configuration",
				"agent_name": f"ZZ Judge Agent {suffix}",
				"agent_id": f"zz_judge_{suffix}",
				"agent_type": "Background",
				"agent_framework": "Direct API",
				"ai_provider": self.provider,
				"ai_model": "zz-judge-off",
			}
		).insert(ignore_permissions=True)

	def test_a_disabled_agent_model_falls_back_to_an_enabled_one(self):
		self.assertEqual(seed.judge_for(self.agent.name), (self.provider, "zz-judge-on"))

	def test_an_enabled_agent_model_is_the_judge(self):
		frappe.db.set_value("AI Agent Configuration", self.agent.name, "ai_model", "zz-judge-on")
		self.assertEqual(seed.judge_for(self.agent.name), (self.provider, "zz-judge-on"))

	def test_repoint_moves_disabled_judge_checks_only(self):
		seed.execute()
		suite = frappe.db.get_value("AI Eval Suite", {"title": seed.SUITE_TITLE})
		case_name = frappe.db.get_value(
			"AI Eval Case", {"suite": suite, "title": "Confirming the proposed topology"}
		)
		case = frappe.get_doc("AI Eval Case", case_name)
		for a in case.assertions:
			if a.assertion_type == "llm_judge":
				a.judge_model = "zz-judge-off"
		case.save(ignore_permissions=True)

		with patch.object(repoint, "judge_for", return_value=(self.provider, "zz-judge-on")):
			repoint.execute()

		case.reload()
		judges = [a.judge_model for a in case.assertions if a.assertion_type == "llm_judge"]
		self.assertEqual(judges, ["zz-judge-on"])
		self.assertTrue(all(not a.judge_model for a in case.assertions if a.assertion_type != "llm_judge"))


class TestMarkEvalChatConversations(FrappeTestCase):
	def test_a_conversation_behind_an_eval_run_is_marked_and_others_are_not(self):
		from one_bpmn.one_bpmn.patches.v1_0 import mark_eval_chat_conversations

		frappe.set_user("Administrator")
		conversations = {}
		for origin in ("eval", "production"):
			chat = frappe.get_doc(
				{"doctype": "Chat Conversation", "title": f"zz-mark-{origin}", "agent_mode": "General Chat"}
			).insert(ignore_permissions=True)
			instance = frappe.get_doc(
				{
					"doctype": "BPMN Process Instance",
					"process_id": f"zz-mark-{frappe.generate_hash(length=6)}",
					"status": "Completed",
					"context_doctype": "Chat Conversation",
					"context_docname": chat.name,
				}
			)
			instance.insert(ignore_permissions=True, ignore_mandatory=True, ignore_links=True)
			frappe.get_doc(
				{
					"doctype": "AI Agent Run",
					"instance": instance.name,
					"bpmn_id": "zz_mark",
					"status": "Success",
					"origin": origin,
					"started_at": frappe.utils.now_datetime(),
				}
			).insert(ignore_permissions=True)
			conversations[origin] = chat.name

		mark_eval_chat_conversations.execute()

		self.assertEqual(frappe.db.get_value("Chat Conversation", conversations["eval"], "is_eval"), 1)
		self.assertEqual(frappe.db.get_value("Chat Conversation", conversations["production"], "is_eval"), 0)
