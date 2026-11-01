import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.agents.agent_config_resolver import get_agent_config_lint_state


def make_agent_config(**values):
	suffix = frappe.generate_hash(length=6)
	return frappe.get_doc(
		{
			"doctype": "AI Agent Configuration",
			"agent_name": f"Lint State Probe {suffix}",
			"agent_id": f"lint_state_probe_{suffix}",
			"agent_framework": "Direct API",
			"agent_type": "Background",
			"enabled": 1,
			"system_prompt": "You triage tickets.",
			**values,
		}
	).insert()


def lint_state(name):
	return get_agent_config_lint_state(frappe.as_json([name]))[name]


class TestAgentConfigLintState(FrappeTestCase):
	def test_a_config_that_does_not_exist_is_reported_absent(self):
		self.assertEqual(lint_state("No Such Agent"), {"exists": False})

	def test_a_config_with_no_ai_model_lists_the_gap(self):
		config = make_agent_config()
		state = lint_state(config.name)
		self.assertTrue(state["exists"])
		self.assertEqual(state["lifecycle_status"], frappe.db.get_value(config.doctype, config.name, "lifecycle_status") or "Draft")
		self.assertTrue(any("AI Model" in problem for problem in state["problems"]))

	def test_a_background_agent_may_keep_an_empty_prompt(self):
		config = make_agent_config(system_prompt="")
		self.assertFalse(any("System prompt" in problem for problem in lint_state(config.name)["problems"]))

	def test_a_chat_agent_with_an_empty_prompt_is_flagged(self):
		config = make_agent_config(agent_type="Chat", chat_mode_label="Lint Probe")
		frappe.db.set_value(config.doctype, config.name, "system_prompt", "")
		self.assertTrue(any("System prompt" in problem for problem in lint_state(config.name)["problems"]))

	def test_a_disabled_config_is_reported_disabled(self):
		config = make_agent_config(enabled=0)
		self.assertFalse(lint_state(config.name)["enabled"])

	def test_a_user_who_cannot_read_configs_is_refused(self):
		self.addCleanup(frappe.set_user, "Administrator")
		frappe.set_user("Guest")
		with self.assertRaises(frappe.PermissionError):
			get_agent_config_lint_state("[]")
