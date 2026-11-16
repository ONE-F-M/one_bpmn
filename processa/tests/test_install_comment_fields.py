from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from processa.install import after_install

COMMENT_FIELDS = ("is_processa_comment", "custom_element_id", "custom_is_task", "custom_status", "custom_assigned_to")


def _comment_fields():
	return set(frappe.get_all("Custom Field", filters={"dt": "Comment", "fieldname": ["in", COMMENT_FIELDS]}, pluck="fieldname"))


class TestInstallCommentFields(FrappeTestCase):
	def test_after_install_creates_comment_fields(self):
		frappe.db.delete("Custom Field", {"dt": "Comment", "fieldname": ["in", COMMENT_FIELDS]})
		frappe.clear_cache(doctype="Comment")
		self.assertEqual(_comment_fields(), set())
		with patch("frappe.db.commit"):
			after_install()
		self.assertEqual(_comment_fields(), set(COMMENT_FIELDS))

	def test_second_run_does_not_duplicate(self):
		with patch("frappe.db.commit"):
			after_install()
			after_install()
		count = frappe.db.count("Custom Field", {"dt": "Comment", "fieldname": ["in", COMMENT_FIELDS]})
		self.assertEqual(count, len(COMMENT_FIELDS))
