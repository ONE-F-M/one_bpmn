import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.agents._eval_test_factories import make_agent_configuration
from one_bpmn.agents.skill_seeding import seed_skills


def _spec(name, body="# step one"):
	return {
		"skill_name": name,
		"description": "Use this skill when seeding tests run. Do NOT use it for real work.",
		"body": body,
		"resources": [
			{"resource_type": "Reference", "resource_name": "notes", "resource_value": "see body"},
		],
	}


class TestSkillSeeding(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self.agent = make_agent_configuration(agent_type="Background")
		self.name = "_Test seeded skill " + frappe.generate_hash(length=6)

	def test_a_seeded_skill_is_active_with_its_resource_and_enabled_on_the_agent(self):
		seed_skills(self.agent.name, [_spec(self.name)])

		skill = frappe.get_doc("AI Skill", self.name)
		self.assertEqual(skill.status, "Active")
		self.assertEqual([r.resource_name for r in skill.resources], ["notes"])
		config = frappe.get_doc("AI Agent Configuration", self.agent.name)
		self.assertEqual([r.skill for r in config.enabled_skills], [self.name])

	def test_seeding_twice_refreshes_the_body_and_adds_no_second_row(self):
		seed_skills(self.agent.name, [_spec(self.name)])
		seed_skills(self.agent.name, [_spec(self.name, body="# step two")])

		self.assertEqual(frappe.db.get_value("AI Skill", self.name, "body"), "# step two")
		self.assertEqual(frappe.db.count("AI Skill Resource", {"parent": self.name}), 1)
		self.assertEqual(
			frappe.db.count("AI Agent Enabled Skill", {"parent": self.agent.name, "skill": self.name}), 1
		)

	def test_a_missing_agent_still_gets_the_skill(self):
		names = seed_skills("_No Such Agent " + frappe.generate_hash(length=6), [_spec(self.name)])

		self.assertEqual(names, [self.name])
		self.assertTrue(frappe.db.exists("AI Skill", self.name))

	def test_a_description_without_trigger_phrasing_fails_the_seed(self):
		spec = _spec(self.name)
		spec["description"] = "Helps with things."
		with self.assertRaises(frappe.ValidationError):
			seed_skills(self.agent.name, [spec])
