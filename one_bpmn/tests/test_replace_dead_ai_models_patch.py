# Copyright (c) 2026, one-fm and contributors
"""The patch that moves agents, grading and compaction off AI Models whose key is rejected."""

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.one_bpmn.patches.v1_0 import replace_dead_ai_models as P

PREFIX = "ZZ Dead Models"
DEAD_HAIKU = f"{PREFIX} dead-haiku"
DEAD_SONNET = f"{PREFIX} dead-sonnet"
SHARED = f"{PREFIX} shared - claude-haiku-5-5"
AGENT = f"{PREFIX} Agent"


class TestReplaceDeadAiModels(FrappeTestCase):
	def setUp(self):
		self.cleanup()
		self.provider = frappe.db.get_value("AI Provider", {}, "name")
		self.make_model(DEAD_HAIKU, "claude-haiku-4-5", "Unhealthy")
		self.make_model(DEAD_SONNET, "claude-sonnet-5", "Unhealthy")
		self.make_model(SHARED, "claude-haiku-5-5", "Healthy")
		self.make_model(f"{AGENT} - claude-haiku-5-5", "claude-haiku-5-5", "Healthy")
		self.agent = self.make_agent(AGENT, DEAD_HAIKU)
		self.settings_patch = patch.multiple(P, SHARED_MODEL=SHARED, PLATFORM_OWNERS=("Administrator",))
		self.settings_patch.start()
		frappe.db.set_single_value("Processa Settings", "nightly_eval_grading_model", None)

	def tearDown(self):
		self.settings_patch.stop()
		self.cleanup()

	def cleanup(self):
		frappe.db.delete("AI Agent Configuration", {"agent_name": ("like", f"{PREFIX}%")})
		frappe.db.delete("AI Model", {"model_name": ("like", f"{PREFIX}%")})

	def make_model(self, name, api_name, status, enabled=1):
		frappe.get_doc(
			{
				"doctype": "AI Model",
				"model_name": name,
				"provider": self.provider,
				"model_api_name": api_name,
				"enable_model": 0,
			}
		).insert(ignore_permissions=True)
		frappe.db.set_value("AI Model", name, {"enable_model": enabled, "health_status": status})

	def make_agent(self, name, model, **extra):
		return frappe.get_doc(
			{
				"doctype": "AI Agent Configuration",
				"agent_name": name,
				"agent_id": frappe.scrub(name),
				"agent_type": "Background",
				"agent_framework": "Direct API",
				"enabled": 1,
				"ai_model": model,
				**extra,
			}
		).insert(ignore_permissions=True)

	def value(self, field, agent=AGENT):
		return frappe.db.get_value("AI Agent Configuration", agent, field)

	def test_agent_on_a_dead_model_moves_to_its_own_healthy_successor(self):
		P.repoint_agents()
		self.assertEqual(self.value("ai_model"), f"{AGENT} - claude-haiku-5-5")

	def test_agent_stays_when_its_successor_is_not_healthy(self):
		frappe.db.set_value("AI Model", f"{AGENT} - claude-haiku-5-5", "health_status", "Unknown")
		P.repoint_agents()
		self.assertEqual(self.value("ai_model"), DEAD_HAIKU)

	def test_agent_on_a_healthy_model_is_left_alone(self):
		healthy = self.make_agent(f"{PREFIX} Fine", SHARED)
		P.repoint_agents()
		self.assertEqual(self.value("ai_model", healthy.name), SHARED)

	def test_grading_and_compaction_move_to_the_shared_model(self):
		frappe.db.set_single_value("Processa Settings", "nightly_eval_grading_model", DEAD_HAIKU)
		frappe.db.set_value("AI Agent Configuration", AGENT, "compaction_model", DEAD_HAIKU)
		P.repoint_grading_and_compaction()
		self.assertEqual(frappe.db.get_single_value("Processa Settings", "nightly_eval_grading_model"), SHARED)
		self.assertEqual(self.value("compaction_model"), SHARED)

	def test_grading_stays_when_the_shared_model_is_not_healthy(self):
		frappe.db.set_value("AI Model", SHARED, "health_status", "Unhealthy")
		frappe.db.set_single_value("Processa Settings", "nightly_eval_grading_model", DEAD_HAIKU)
		P.repoint_grading_and_compaction()
		self.assertEqual(
			frappe.db.get_single_value("Processa Settings", "nightly_eval_grading_model"), DEAD_HAIKU
		)

	def test_memory_models_are_never_changed(self):
		frappe.db.set_value(
			"AI Agent Configuration",
			AGENT,
			{"memory_distill_model": DEAD_HAIKU, "memory_reconcile_model": DEAD_SONNET},
		)
		P.execute()
		self.assertEqual(self.value("memory_distill_model"), DEAD_HAIKU)
		self.assertEqual(self.value("memory_reconcile_model"), DEAD_SONNET)

	def test_platform_owners_fill_empty_recipient_lists_once(self):
		settings = frappe.get_doc("Processa Settings")
		for field in P.RECIPIENT_FIELDS:
			settings.set(field, [])
		settings.save(ignore_permissions=True)

		P.add_platform_owners()
		P.add_platform_owners()

		settings = frappe.get_doc("Processa Settings")
		for field in P.RECIPIENT_FIELDS:
			self.assertEqual([row.user for row in settings.get(field)], ["Administrator"])

	def test_stale_reason_is_cleared_only_when_the_agent_validates(self):
		frappe.db.set_value(
			"AI Agent Configuration",
			AGENT,
			{"lifecycle_status": "Live", "needs_attention_reason": "old", "ai_model": SHARED},
		)
		P.clear_stale_reasons()
		self.assertFalse(self.value("needs_attention_reason"))

		frappe.db.set_value("AI Model", SHARED, "enable_model", 0)
		frappe.db.set_value("AI Agent Configuration", AGENT, "needs_attention_reason", "still broken")
		P.clear_stale_reasons()
		self.assertEqual(self.value("needs_attention_reason"), "still broken")

	def test_shape_link_takes_the_exact_case_of_the_configuration(self):
		names = {"prosally": "Prosally", "logix - writer": "Logix - Writer"}
		xml = '<x aiAgentConfig="prosally"/><y aiAgentConfig="Logix - Writer"/><z aiAgentConfig="other"/>'
		spec = '{"aiAgentConfig": "prosally"}'

		self.assertEqual(
			P.relink(xml, P.XML_LINK, names),
			'<x aiAgentConfig="Prosally"/><y aiAgentConfig="Logix - Writer"/><z aiAgentConfig="other"/>',
		)
		self.assertEqual(P.relink(spec, P.SPEC_LINK, names), '{"aiAgentConfig": "Prosally"}')
		self.assertEqual(P.relink(None, P.XML_LINK, names), "")

	def test_dead_model_is_disabled_unless_something_still_uses_it(self):
		P.disable_unused_dead_models()
		self.assertEqual(frappe.db.get_value("AI Model", DEAD_SONNET, "enable_model"), 0)
		self.assertEqual(frappe.db.get_value("AI Model", DEAD_HAIKU, "enable_model"), 1)

	def test_running_twice_changes_nothing_more(self):
		P.execute()
		before = (self.value("ai_model"), self.value("modified"))
		P.execute()
		self.assertEqual((self.value("ai_model"), self.value("modified")), before)
