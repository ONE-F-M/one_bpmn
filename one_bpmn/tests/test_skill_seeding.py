import os
import re

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.agents._eval_test_factories import make_agent_configuration
from one_bpmn.agents.skill_seeding import load_skill_dir, seed_agent_skills, seed_skills, skills_root
from one_bpmn.one_bpmn.patches.v1_0.seed_specialist_agent_skills import _SKILLS


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


class TestShippedSkills(FrappeTestCase):
	"""The folders under agent_skills are what the patch installs, so a folder
	the AI Skill controller would reject has to fail here and not on a site."""

	def setUp(self):
		frappe.set_user("Administrator")

	def test_every_shipped_folder_loads_and_installs(self):
		agent = make_agent_configuration(agent_type="Background")
		for dir_name in sorted(_all_dirs()):
			with self.subTest(skill=dir_name):
				spec = load_skill_dir(dir_name)
				self.assertTrue(spec["skill_name"])
				self.assertTrue(spec["body"])
				lowered = spec["description"].lower()
				self.assertIn("use this skill when", lowered)
				self.assertIn("do not use", lowered)
				seed_skills(agent.name, [spec])
				self.assertEqual(frappe.db.get_value("AI Skill", spec["skill_name"], "status"), "Active")

	def test_a_body_link_names_a_resource_that_exists(self):
		for dir_name in sorted(_all_dirs()):
			spec = load_skill_dir(dir_name)
			shipped = {row["resource_name"] for row in spec["resources"]}
			for link in _links(spec["body"]):
				with self.subTest(skill=dir_name, link=link):
					self.assertIn(link, shipped)

	def test_the_patch_names_only_folders_that_exist(self):
		named = {name for names in _SKILLS.values() for name in names}
		self.assertTrue(named)
		self.assertFalse(named - set(_all_dirs()))

	def test_seeding_one_agent_enables_exactly_its_skills(self):
		agent = make_agent_configuration(agent_type="Background")
		dirs = _SKILLS["Connector Agent"]

		seed_agent_skills(agent.name, dirs)

		config = frappe.get_doc("AI Agent Configuration", agent.name)
		self.assertEqual(len(config.enabled_skills), len(dirs))


def _all_dirs() -> list[str]:
	root = skills_root()
	return [name for name in os.listdir(root) if os.path.isdir(os.path.join(root, name))]


def _links(body: str) -> set[str]:
	return set(re.findall(r"\]\(((?:references|resources)/[^)#]+)", body))
