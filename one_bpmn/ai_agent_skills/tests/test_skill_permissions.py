import frappe
from frappe.client import get_list, set_value
from frappe.tests.utils import FrappeTestCase

from one_bpmn.ai_agent_skills.permissions import (
	ai_skill_activation_query_conditions,
	ai_skill_query_conditions,
)

PREFIX = "zzperm"
OWNER_A = f"{PREFIX}_owner_a@example.com"
OWNER_B = f"{PREFIX}_owner_b@example.com"
NO_ROLE = f"{PREFIX}_norole@example.com"


def remove_fixtures() -> None:
	"""Delete every record these tests create; they run again from a clean state."""
	skills = frappe.get_all("AI Skill", filters={"name": ["like", f"{PREFIX}-%"]}, pluck="name")
	groups = (
		("AI Skill Activation", frappe.get_all("AI Skill Activation", filters={"skill": ["in", skills or [""]]}, pluck="name")),
		("AI Agent Configuration", frappe.get_all("AI Agent Configuration", filters={"name": ["like", f"{PREFIX}-%"]}, pluck="name")),
		("BPMN Process Model", frappe.get_all("BPMN Process Model", filters={"title": ["like", f"{PREFIX}-%"]}, pluck="name")),
		("Process", frappe.get_all("Process", filters={"name": ["like", f"{PREFIX}-%"]}, pluck="name")),
		("AI Skill", skills),
		("User", [email for email in (OWNER_A, OWNER_B, NO_ROLE) if frappe.db.exists("User", email)]),
	)
	for doctype, names in groups:
		for name in names:
			frappe.delete_doc(doctype, name, force=True, ignore_permissions=True)  # perms: test fixture
	frappe.db.commit()


def make_user(email: str, roles: list[str]) -> None:
	frappe.get_doc(
		{
			"doctype": "User",
			"email": email,
			"first_name": email.split("@")[0],
			"send_welcome_email": 0,
			"roles": [{"role": role} for role in roles],
		}
	).insert(ignore_permissions=True)  # perms: test fixture


def make_agent(name: str, process_owner: str | None = None, process_model: str | None = None, skills=()) -> None:
	frappe.get_doc(
		{
			"doctype": "AI Agent Configuration",
			"agent_name": name,
			"agent_id": name.replace("-", "_"),
			"agent_framework": "Direct API",
			"process_owner": process_owner,
			"process_model": process_model,
			"enabled_skills": [{"skill": skill} for skill in skills],
		}
	).insert(ignore_permissions=True)  # perms: test fixture


def make_skill(name: str, as_user: str = "Administrator") -> None:
	frappe.set_user(as_user)
	frappe.get_doc(
		{
			"doctype": "AI Skill",
			"skill_name": name,
			"status": "Draft",
			"tier": "Draft-Only",
			"description": "Permission fixture. Do not use.",
			"body": "before",
		}
	).insert(ignore_permissions=True)  # perms: test fixture
	frappe.set_user("Administrator")
	frappe.get_doc({"doctype": "AI Skill Activation", "skill": name}).insert(
		ignore_permissions=True  # perms: test fixture
	)


class TestSkillPermissions(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.set_user("Administrator")
		remove_fixtures()
		cls.addClassCleanup(remove_fixtures)
		make_user(OWNER_A, ["Process Owner"])
		make_user(OWNER_B, ["Process Owner"])
		make_user(NO_ROLE, [])

		cls.direct = f"{PREFIX}-direct"
		cls.via_process = f"{PREFIX}-via-process"
		cls.shared = f"{PREFIX}-shared"
		cls.unlinked = f"{PREFIX}-unlinked"
		cls.made_by_owner = f"{PREFIX}-made-by-owner"
		for name in (cls.direct, cls.via_process, cls.shared, cls.unlinked):
			make_skill(name)
		make_skill(cls.made_by_owner, as_user=OWNER_A)

		frappe.get_doc(
			{
				"doctype": "Process",
				"process_name": f"{PREFIX}-process",
				"description": "Permission fixture",
				"process_owner": OWNER_B,
			}
		).insert(ignore_permissions=True)  # perms: test fixture
		model = frappe.get_doc(
			{
				"doctype": "BPMN Process Model",
				"title": f"{PREFIX}-model",
				"process_id": f"{PREFIX}_model",
				"version": 1,
				"process_name": f"{PREFIX}-process",
			}
		).insert(ignore_permissions=True)  # perms: test fixture
		make_agent(f"{PREFIX}-agent-direct", process_owner=OWNER_A, skills=[cls.direct, cls.shared])
		make_agent(f"{PREFIX}-agent-via-process", process_model=model.name, skills=[cls.via_process, cls.shared])

	def tearDown(self):
		frappe.set_user("Administrator")
		super().tearDown()

	def names_seen_by(self, user: str, doctype: str = "AI Skill") -> set[str]:
		frappe.set_user(user)
		key = "skill" if doctype == "AI Skill Activation" else "name"
		rows = get_list(doctype, fields=[key], limit_page_length=0)
		return {row[key] for row in rows if row[key].startswith(PREFIX)}

	def test_system_manager_sees_every_skill_and_edits_a_body(self):
		seen = self.names_seen_by("Administrator")
		self.assertEqual(seen, {self.direct, self.via_process, self.shared, self.unlinked, self.made_by_owner})

		set_value("AI Skill", self.unlinked, "body", "edited by a system manager")
		self.assertEqual(frappe.db.get_value("AI Skill", self.unlinked, "body"), "edited by a system manager")

	def test_process_owner_sees_skills_linked_directly_or_through_the_process(self):
		self.assertEqual(self.names_seen_by(OWNER_A), {self.direct, self.shared, self.made_by_owner})
		self.assertEqual(self.names_seen_by(OWNER_B), {self.via_process, self.shared})

	def test_process_owner_edits_only_skills_linked_to_their_processes(self):
		frappe.set_user(OWNER_A)
		set_value("AI Skill", self.direct, "body", "edited by owner a")
		self.assertEqual(frappe.db.get_value("AI Skill", self.direct, "body"), "edited by owner a")

		for hidden in (self.via_process, self.unlinked):
			with self.assertRaises(frappe.PermissionError):
				set_value("AI Skill", hidden, "body", "must not be saved")
			self.assertEqual(frappe.db.get_value("AI Skill", hidden, "body"), "before")

	def test_both_owners_of_a_shared_skill_can_edit_it(self):
		for user in (OWNER_A, OWNER_B):
			frappe.set_user(user)
			set_value("AI Skill", self.shared, "body", f"edited by {user}")
			self.assertEqual(frappe.db.get_value("AI Skill", self.shared, "body"), f"edited by {user}")

	def test_unlinked_skill_is_limited_to_its_creator_and_system_manager(self):
		self.assertIn(self.made_by_owner, self.names_seen_by(OWNER_A))
		self.assertNotIn(self.made_by_owner, self.names_seen_by(OWNER_B))
		self.assertIn(self.made_by_owner, self.names_seen_by("Administrator"))
		self.assertNotIn(self.unlinked, self.names_seen_by(OWNER_A))

	def test_user_with_neither_role_gets_a_permission_error(self):
		frappe.set_user(NO_ROLE)
		with self.assertRaises(frappe.PermissionError):
			get_list("AI Skill", fields=["name"])
		with self.assertRaises(frappe.PermissionError):
			get_list("AI Skill Activation", fields=["name"])
		with self.assertRaises(frappe.PermissionError):
			set_value("AI Skill", self.direct, "body", "must not be saved")

	def test_process_owner_reads_activations_of_their_own_skills_only(self):
		self.assertEqual(
			self.names_seen_by(OWNER_A, "AI Skill Activation"), {self.direct, self.shared, self.made_by_owner}
		)
		self.assertEqual(self.names_seen_by(OWNER_B, "AI Skill Activation"), {self.via_process, self.shared})
		self.assertEqual(
			self.names_seen_by("Administrator", "AI Skill Activation"),
			{self.direct, self.via_process, self.shared, self.unlinked, self.made_by_owner},
		)

	def test_activation_log_is_read_only_for_a_process_owner(self):
		self.assertTrue(frappe.has_permission("AI Skill Activation", "read", user=OWNER_A))
		for ptype in ("create", "write", "delete"):
			self.assertFalse(frappe.has_permission("AI Skill Activation", ptype, user=OWNER_A), ptype)

	def test_system_manager_gets_no_restriction(self):
		self.assertEqual(ai_skill_query_conditions("Administrator"), "")
		self.assertEqual(ai_skill_activation_query_conditions("Administrator"), "")
		self.assertIn("`tabAI Skill`.`name` in (", ai_skill_query_conditions(OWNER_A))
