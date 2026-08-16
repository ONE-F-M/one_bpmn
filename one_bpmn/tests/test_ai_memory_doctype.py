# Copyright (c) 2026, one-fm and contributors
# Tests for the AI Memory doctype: scope creation, scope-key validation,
# dedup overwrite vs insert, index presence, and permission scenarios.

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase


def _memory(**kw):
	doc = frappe.get_doc(dict(doctype="AI Memory", **kw))
	doc.insert(ignore_permissions=True)
	return doc


def _make_process_model():
	doc = frappe.get_doc(
		{
			"doctype": "BPMN Process Model",
			"title": f"Test PM {frappe.generate_hash(length=6)}",
			"process_id": frappe.generate_hash(length=6),
			"version": 1,
		}
	)
	doc.insert(ignore_permissions=True)
	return doc.name


def _make_user_with_role(role):
	user = frappe.get_doc(
		{
			"doctype": "User",
			"email": f"pd_{frappe.generate_hash(length=6)}@example.com",
			"first_name": "PD",
			"send_welcome_email": 0,
			"roles": [{"role": role}],
		}
	)
	user.insert(ignore_permissions=True)
	return user.name


class TestAIMemoryDoctype(FrappeTestCase):
	# ── creation for each scope ──
	def test_create_agent_scope(self):
		m = _memory(memory_scope="Agent", agent_element="Activity_1", content="a")
		self.assertTrue(m.name)

	def test_create_process_scope(self):
		pm = _make_process_model()
		m = _memory(memory_scope="Process", process_model=pm, content="p")
		self.assertEqual(m.process_model, pm)

	def test_create_entity_scope(self):
		m = _memory(
			memory_scope="Entity",
			reference_doctype="User",
			reference_name="Administrator",
			content="e",
		)
		self.assertEqual(m.reference_doctype, "User")

	# ── scope-key validation failures ──
	def test_scope_key_validation_failures(self):
		with self.assertRaises(frappe.ValidationError):
			_memory(memory_scope="Agent", content="x")
		with self.assertRaises(frappe.ValidationError):
			_memory(memory_scope="Process", content="x")
		with self.assertRaises(frappe.ValidationError):
			_memory(memory_scope="Entity", content="x")

	# ── dedup overwrite vs insert ──
	def test_dedup_overwrite(self):
		_memory(memory_scope="Agent", agent_element="A", content="v1", dedup_key="k")
		_memory(memory_scope="Agent", agent_element="A", content="v2", dedup_key="k")
		rows = frappe.get_all(
			"AI Memory",
			filters={"memory_scope": "Agent", "agent_element": "A", "dedup_key": "k"},
			fields=["content"],
		)
		self.assertEqual(len(rows), 1)
		self.assertEqual(rows[0]["content"], "v2")

	def test_insert_without_dedup_key(self):
		_memory(memory_scope="Agent", agent_element="B", content="x")
		_memory(memory_scope="Agent", agent_element="B", content="y")
		self.assertEqual(
			frappe.db.count("AI Memory", {"memory_scope": "Agent", "agent_element": "B"}), 2
		)

	# ── index presence ──
	def test_indexes_present(self):
		names = {r["Key_name"] for r in frappe.db.sql("SHOW INDEX FROM `tabAI Memory`", as_dict=True)}
		self.assertIn("memory_scope_agent_element_index", names)
		self.assertIn("reference_doctype_reference_name_index", names)

	# ── permissions: Process Designer read allowed, delete denied ──
	def test_process_designer_permissions(self):
		m = _memory(memory_scope="Agent", agent_element="P", content="secret")
		user = _make_user_with_role("Process Designer")
		self.assertTrue(frappe.has_permission("AI Memory", "read", doc=m.name, user=user))
		self.assertFalse(frappe.has_permission("AI Memory", "delete", doc=m.name, user=user))

		self.addCleanup(frappe.set_user, "Administrator")
		frappe.set_user(user)
		with self.assertRaises(frappe.PermissionError):
			frappe.delete_doc("AI Memory", m.name)
