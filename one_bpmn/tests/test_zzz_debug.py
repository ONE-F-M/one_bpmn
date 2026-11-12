import traceback

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.api.common import distinct


class TestZzzDebug(FrappeTestCase):
	def test_debug(self):
		out = []
		for label, fn in (
			("limit", lambda: distinct("ToDo", "status", limit=1)),
			("reftype", lambda: distinct("ToDo", "reference_type")),
			("status", lambda: distinct("ToDo", "status")),
		):
			try:
				out.append(f"{label} ok {fn()}")
			except Exception:
				out.append(f"{label} ERR " + traceback.format_exc()[-400:])
		self.fail("\nDBG\n" + "\n".join(out))
