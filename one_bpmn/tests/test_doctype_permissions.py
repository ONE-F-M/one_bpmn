import frappe
from frappe.client import get_list
from frappe.tests.utils import FrappeTestCase

from one_bpmn.install import grant_process_owner_doctype_access

PREFIX = "ZZPerm"
OWNER = "zzperm_owner@example.com"
OUTSIDER = "zzperm_outsider@example.com"
LISTED = f"{PREFIX} Listed"
UNLISTED = f"{PREFIX} Unlisted"
CREATED = f"{PREFIX} Created"


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


def make_doctype(name: str, as_user: str = "Administrator") -> None:
	frappe.set_user(as_user)
	frappe.get_doc(
		{
			"doctype": "DocType",
			"name": name,
			"module": "One Bpmn",
			"custom": 1,
			"fields": [{"fieldname": "title", "fieldtype": "Data", "label": "Title"}],
			"permissions": [{"role": "System Manager", "read": 1}],
		}
	).insert()
	frappe.set_user("Administrator")


def remove_fixtures() -> None:
	frappe.set_user("Administrator")
	for name in frappe.get_all("Process", filters={"name": ["like", f"{PREFIX}%"]}, pluck="name"):
		frappe.delete_doc("Process", name, force=True, ignore_permissions=True)  # perms: test fixture
	for name in (LISTED, UNLISTED, CREATED):
		if frappe.db.exists("DocType", name):
			frappe.delete_doc("DocType", name, force=True, ignore_permissions=True)  # perms: test fixture
	for email in (OWNER, OUTSIDER):
		if frappe.db.exists("User", email):
			frappe.delete_doc("User", email, force=True, ignore_permissions=True)  # perms: test fixture
	frappe.db.commit()


class TestDocTypePermissions(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.set_user("Administrator")
		remove_fixtures()
		cls.addClassCleanup(remove_fixtures)
		grant_process_owner_doctype_access()
		make_user(OWNER, ["Process Owner"])
		make_user(OUTSIDER, ["Process Owner"])
		make_doctype(LISTED)
		make_doctype(UNLISTED)
		frappe.get_doc(
			{
				"doctype": "Process",
				"process_name": f"{PREFIX} Process",
				"description": "Permission fixture",
				"process_owner": OWNER,
				"process_doctypes": [{"document_type": LISTED}],
			}
		).insert(ignore_permissions=True)  # perms: test fixture

	def tearDown(self):
		frappe.set_user("Administrator")
		super().tearDown()

	def names_seen_by(self, user: str) -> set[str]:
		frappe.set_user(user)
		rows = get_list("DocType", fields=["name"], filters={"name": ["like", f"{PREFIX}%"]}, limit_page_length=0)
		return {row["name"] for row in rows}

	def test_system_manager_sees_every_doctype(self):
		self.assertEqual(self.names_seen_by("Administrator"), {LISTED, UNLISTED})

	def test_process_owner_lists_only_doctypes_of_their_processes(self):
		self.assertEqual(self.names_seen_by(OWNER), {LISTED})
		self.assertEqual(self.names_seen_by(OUTSIDER), set())

	def test_process_owner_edits_only_doctypes_of_their_processes(self):
		self.assertTrue(frappe.has_permission("DocType", "write", doc=LISTED, user=OWNER))
		self.assertFalse(frappe.has_permission("DocType", "write", doc=UNLISTED, user=OWNER))
		self.assertFalse(frappe.has_permission("DocType", "write", doc=LISTED, user=OUTSIDER))

	def test_process_owner_creates_a_doctype_and_then_sees_it(self):
		self.addCleanup(frappe.delete_doc, "DocType", CREATED, force=True, ignore_permissions=True)  # perms: test fixture
		make_doctype(CREATED, as_user=OUTSIDER)
		self.assertEqual(self.names_seen_by(OUTSIDER), {CREATED})
		self.assertTrue(frappe.has_permission("DocType", "write", doc=CREATED, user=OUTSIDER))
		self.assertFalse(frappe.has_permission("DocType", "write", doc=CREATED, user=OWNER))
