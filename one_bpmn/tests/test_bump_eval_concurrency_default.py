# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.one_bpmn.patches.v1_0 import bump_eval_concurrency_default


class TestBumpEvalConcurrencyDefault(FrappeTestCase):
	"""Processa Settings is a Single, so the patch must not look for a table of its own."""

	def setUp(self):
		self.original = frappe.db.get_single_value("Processa Settings", "eval_concurrency")

	def tearDown(self):
		frappe.db.set_single_value("Processa Settings", "eval_concurrency", self.original)
		frappe.db.commit()

	def test_the_old_default_of_one_is_raised_to_four(self):
		frappe.db.set_single_value("Processa Settings", "eval_concurrency", 1)
		bump_eval_concurrency_default.execute()
		self.assertEqual(frappe.db.get_single_value("Processa Settings", "eval_concurrency"), 4)

	def test_a_value_someone_chose_is_kept(self):
		frappe.db.set_single_value("Processa Settings", "eval_concurrency", 2)
		bump_eval_concurrency_default.execute()
		self.assertEqual(frappe.db.get_single_value("Processa Settings", "eval_concurrency"), 2)
