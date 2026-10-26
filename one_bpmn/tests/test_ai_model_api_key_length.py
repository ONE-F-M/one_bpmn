# Copyright (c) 2026, one-fm and contributors
"""An AI Model's API key field must take a full provider key: OpenAI project keys run to about 164 characters."""

import json

import frappe
from frappe.tests.utils import FrappeTestCase


class TestAiModelApiKeyLength(FrappeTestCase):
	def test_the_api_key_field_takes_an_openai_project_key(self):
		path = frappe.get_app_path("one_bpmn", "one_bpmn", "doctype", "ai_model", "ai_model.json")
		with open(path) as f:
			fields = {df["fieldname"]: df for df in json.load(f)["fields"]}
		self.assertGreaterEqual(fields["api_key"].get("length", 140), 164)
