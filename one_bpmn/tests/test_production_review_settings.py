# Copyright (c) 2026, one-fm and contributors
"""The canvas learns from one call which branch a doctype sync targets."""

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.api.production_review import PR_BASE_BRANCH, production_review_settings


class TestProductionReviewSettings(FrappeTestCase):
	def test_the_sync_dialog_is_told_the_pull_request_branch(self):
		settings = production_review_settings()
		self.assertEqual(settings["pr_base_branch"], PR_BASE_BRANCH)
		self.assertEqual(settings["pr_base_branch"], "staging")
		self.assertIn("instance_type", settings)
