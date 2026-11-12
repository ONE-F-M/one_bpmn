import traceback

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.api import a2a_admin
from one_bpmn.api.common import distinct


class TestZzzDebug(FrappeTestCase):
	def test_debug(self):
		out = []
		for label, fn in (
			("limit", lambda: distinct("ToDo", "status", limit=1)),
			("reftype", lambda: distinct("ToDo", "reference_type")),
		):
			try:
				out.append(f"{label} ok {fn()}")
			except Exception:
				out.append(f"{label} ERR " + traceback.format_exc()[-600:])
		email = "zz-dbg@example.com"
		if not frappe.db.exists("User", email):
			frappe.get_doc({"doctype": "User", "email": email, "first_name": "ZZ Dbg", "send_welcome_email": 0}).insert(ignore_permissions=True)
		self.set_user(email)
		try:
			out.append(f"roles {frappe.get_roles()}")
			out.append(f"perm {a2a_admin.get_permissions()}")
			a2a_admin.list_clients()
			out.append("list_clients no raise")
		except Exception:
			out.append("clients ERR " + traceback.format_exc()[-500:])
		frappe.set_user("Administrator")
		self.fail("\nDBG\n" + "\n".join(out))
