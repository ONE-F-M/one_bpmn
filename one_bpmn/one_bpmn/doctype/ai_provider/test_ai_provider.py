# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""
Tests for the AI Provider doctype.

Covers:
  (a) Admin can create an AI Provider with all required fields
  (b) as_dict() does NOT contain the api_key value
  (c) doc.get_password("api_key") returns the real key
  (d) frappe.get_list("AI Provider") does NOT include api_key in results
  (e) A non-admin user cannot frappe.get_doc an AI Provider (PermissionError)
  (f) Duplicate provider_name raises DuplicateEntryError
  (g) A disabled provider (enabled=0) is still readable by an admin
"""
import frappe
from frappe.model.document import Document
from frappe.tests.utils import FrappeTestCase


def make_ai_provider(**kwargs) -> Document:
    """Factory function for AI Provider test fixtures."""

    defaults = {
        "doctype": "AI Provider",
        "provider_name": f"test-provider-{frappe.generate_hash(length=6)}",
        "provider_type": "OpenAI",
        "api_endpoint": "https://api.openai.com/v1",
        "api_key": "test-placeholder-key",
        "default_model": "gpt-4o",
        "enabled": 1,
    }
    defaults.update(kwargs)
    doc = frappe.get_doc(defaults)
    doc.insert(ignore_permissions=True)
    return doc


class TestAIProvider(FrappeTestCase):
    def test_create_ai_provider(self):
        doc = make_ai_provider()
        self.assertTrue(frappe.db.exists("AI Provider", doc.name))

    def test_api_key_not_in_as_dict(self):
        doc = make_ai_provider()
        loaded = frappe.get_doc("AI Provider", doc.name)
        d = loaded.as_dict()
        # The Password fieldtype must not expose the stored value in as_dict()

        self.assertFalse(d.get("api_key"))

    def test_get_password_returns_real_key(self):
        doc = make_ai_provider(api_key="secret-test-key")
        loaded = frappe.get_doc("AI Provider", doc.name)
        decrypted = loaded.get_password("api_key")
        self.assertEqual(decrypted, "secret-test-key")

    def test_get_list_excludes_api_key(self):
        doc = make_ai_provider()
        results = frappe.get_list(
            "AI Provider",
            filters={"name": doc.name},
            fields=["name", "provider_name", "api_key"],
        )
        # The expected row must be returned, and the Password value must not be exposed.

        self.assertEqual(len(results), 1)
        self.assertFalse(results[0].get("api_key"))

    def test_non_admin_cannot_read(self):
        doc = make_ai_provider()
        frappe.set_user("Guest")
        try:
            with self.assertRaises(frappe.PermissionError):
                frappe.get_doc("AI Provider", doc.name)
        finally:
            frappe.set_user("Administrator")

    def test_duplicate_provider_name_raises(self):
        name = f"dup-{frappe.generate_hash(length=6)}"
        make_ai_provider(provider_name=name)
        with self.assertRaises(frappe.DuplicateEntryError):
            make_ai_provider(provider_name=name)

    def test_disabled_provider_readable_by_admin(self):
        doc = make_ai_provider(enabled=0)
        loaded = frappe.get_doc("AI Provider", doc.name)
        self.assertEqual(loaded.enabled, 0)
