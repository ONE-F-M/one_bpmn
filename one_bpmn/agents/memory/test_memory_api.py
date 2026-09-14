"""WI-000366: tests for the AI Memory browser API and its permission scoping."""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_to_date, now_datetime

from one_bpmn.api import memory_api

test_ignore = ["BPMN Process Model", "Process"]


def _memory(**kw):
	doc = frappe.get_doc(dict(doctype="AI Memory", **kw))
	doc.insert(ignore_permissions=True)
	return doc


def _make_process(owner: str) -> str:
	doc = frappe.get_doc({
		"doctype": "Process",
		"process_name": f"_Test Memory Process {frappe.generate_hash(length=6)}",
		"description": "test",
		"process_owner": owner,
	})
	doc.insert(ignore_permissions=True)
	return doc.name


def _make_process_model(process_name: str = None) -> str:
	doc = frappe.get_doc({
		"doctype": "BPMN Process Model",
		"title": f"_Test Memory PM {frappe.generate_hash(length=6)}",
		"process_id": frappe.generate_hash(length=6),
		"process_name": process_name,
		"version": 1,
	})
	doc.flags.ignore_mandatory = True
	doc.insert(ignore_permissions=True, ignore_mandatory=True)
	return doc.name


def _make_user_with_role(role: str) -> str:
	user = frappe.get_doc({
		"doctype": "User",
		"email": f"_test_mem_{frappe.generate_hash(length=6)}@example.com",
		"first_name": "MemTest",
		"send_welcome_email": 0,
		"roles": [{"role": role}],
	})
	user.insert(ignore_permissions=True)
	return user.name


class TestMemoryApiListing(FrappeTestCase):
	def setUp(self):
		super().setUp()
		self.owner = _make_user_with_role("Process Owner")
		self.addCleanup(frappe.set_user, "Administrator")
		self.process = _make_process(self.owner)
		self.process_model = _make_process_model(self.process)

	def test_text_search_filters_content(self):
		_memory(memory_scope="Process", process_model=self.process_model, content="apples are tasty")
		_memory(memory_scope="Process", process_model=self.process_model, content="oranges are sour")
		frappe.set_user(self.owner)
		result = memory_api.list_memories(text="apples")
		contents = [m["content"] for m in result["memories"]]
		self.assertEqual(len(contents), 1)
		self.assertIn("apples", contents[0])

	def test_scope_filter(self):
		_memory(memory_scope="Agent", agent_element="Activity_1", content="agent fact")
		_memory(memory_scope="Process", process_model=self.process_model, content="process fact")
		frappe.set_user(self.owner)
		result = memory_api.list_memories(scope="Process")
		self.assertTrue(all(m["memory_scope"] == "Process" for m in result["memories"]))

	def test_agent_filter(self):
		_memory(memory_scope="Agent", agent_element="Activity_A", content="a", user=self.owner)
		_memory(memory_scope="Agent", agent_element="Activity_B", content="b", user=self.owner)
		frappe.set_user(self.owner)
		result = memory_api.list_memories(agent_element="Activity_A")
		self.assertEqual(len(result["memories"]), 1)
		self.assertEqual(result["memories"][0]["agent_element"], "Activity_A")

	def test_process_filter(self):
		other_pm = _make_process_model(self.process)
		_memory(memory_scope="Process", process_model=self.process_model, content="p1")
		_memory(memory_scope="Process", process_model=other_pm, content="p2")
		frappe.set_user(self.owner)
		result = memory_api.list_memories(process_model=self.process_model)
		self.assertEqual(len(result["memories"]), 1)
		self.assertEqual(result["memories"][0]["process_model"], self.process_model)

	def test_source_type_filter(self):
		_memory(memory_scope="Process", process_model=self.process_model, content="a",
				source_type="User Statement")
		_memory(memory_scope="Process", process_model=self.process_model, content="b",
				source_type="Tool Output")
		frappe.set_user(self.owner)
		result = memory_api.list_memories(source_type="Tool Output")
		self.assertTrue(all(m["source_type"] == "Tool Output" for m in result["memories"]))

	def test_include_retired_default_hides_expired(self):
		expired = _memory(memory_scope="Process", process_model=self.process_model, content="gone")
		frappe.db.set_value("AI Memory", expired.name, "expires_on", add_to_date(now_datetime(), days=-1))
		_memory(memory_scope="Process", process_model=self.process_model, content="alive")
		frappe.set_user(self.owner)
		result = memory_api.list_memories()
		names = [m["name"] for m in result["memories"]]
		self.assertNotIn(expired.name, names)

		result_with_retired = memory_api.list_memories(include_retired=True)
		names_with_retired = [m["name"] for m in result_with_retired["memories"]]
		self.assertIn(expired.name, names_with_retired)

	def test_paging(self):
		for i in range(5):
			_memory(memory_scope="Process", process_model=self.process_model, content=f"paged {i}")
		frappe.set_user(self.owner)
		page1 = memory_api.list_memories(page_length=2, start=0)
		page2 = memory_api.list_memories(page_length=2, start=2)
		self.assertEqual(len(page1["memories"]), 2)
		self.assertEqual(len(page2["memories"]), 2)
		self.assertEqual(page1["total"], 5)
		self.assertNotEqual(
			[m["name"] for m in page1["memories"]], [m["name"] for m in page2["memories"]]
		)


class TestMemoryApiRetireRestore(FrappeTestCase):
	def setUp(self):
		super().setUp()
		self.owner = _make_user_with_role("Process Owner")
		self.addCleanup(frappe.set_user, "Administrator")
		self.process = _make_process(self.owner)
		self.process_model = _make_process_model(self.process)

	def test_retire_sets_expires_on(self):
		m = _memory(memory_scope="Process", process_model=self.process_model, content="to retire")
		frappe.set_user(self.owner)
		memory_api.retire_memory(m.name)
		self.assertIsNotNone(frappe.db.get_value("AI Memory", m.name, "expires_on"))

	def test_restore_clears_expires_on(self):
		m = _memory(memory_scope="Process", process_model=self.process_model, content="to restore")
		frappe.db.set_value("AI Memory", m.name, "expires_on", now_datetime())
		frappe.set_user(self.owner)
		memory_api.restore_memory(m.name)
		self.assertIsNone(frappe.db.get_value("AI Memory", m.name, "expires_on"))


class TestMemoryApiDetailAndOptions(FrappeTestCase):
	def setUp(self):
		super().setUp()
		self.owner = _make_user_with_role("Process Owner")
		self.addCleanup(frappe.set_user, "Administrator")
		self.process = _make_process(self.owner)
		self.process_model = _make_process_model(self.process)

	def test_get_memory_returns_full_detail(self):
		m = _memory(
			memory_scope="Process", process_model=self.process_model,
			content="detail check", metadata='{"a": 1}',
		)
		frappe.set_user(self.owner)
		data = memory_api.get_memory(m.name)
		self.assertEqual(data["content"], "detail check")
		self.assertEqual(data["process_model"], self.process_model)
		self.assertIn("scope_key", data)

	def test_get_filter_options_returns_dropdown_values(self):
		_memory(memory_scope="Agent", agent_element="Activity_opts", content="x")
		frappe.set_user(self.owner)
		options = memory_api.get_filter_options()
		self.assertIn("Activity_opts", options["agents"])
		self.assertIn("Agent", options["scopes"])


class TestMemoryApiPermissionFailures(FrappeTestCase):
	"""A user who owns no processes and has no personal memories sees and can
	act on nothing that belongs to somebody else."""

	def setUp(self):
		super().setUp()
		self.owner = _make_user_with_role("Process Owner")
		self.stranger = _make_user_with_role("Process Owner")
		self.addCleanup(frappe.set_user, "Administrator")
		self.process = _make_process(self.owner)
		self.process_model = _make_process_model(self.process)

	def test_stranger_does_not_see_others_memories_in_list(self):
		_memory(memory_scope="Process", process_model=self.process_model, content="owner's secret")
		frappe.set_user(self.stranger)
		result = memory_api.list_memories()
		self.assertEqual(result["memories"], [])
		self.assertEqual(result["total"], 0)

	def test_stranger_cannot_read_single_memory(self):
		m = _memory(memory_scope="Process", process_model=self.process_model, content="owner's secret")
		frappe.set_user(self.stranger)
		with self.assertRaises(frappe.PermissionError):
			memory_api.get_memory(m.name)

	def test_stranger_cannot_retire_others_memory(self):
		m = _memory(memory_scope="Process", process_model=self.process_model, content="owner's secret")
		frappe.set_user(self.stranger)
		with self.assertRaises(frappe.PermissionError):
			memory_api.retire_memory(m.name)

	def test_stranger_cannot_restore_others_memory(self):
		m = _memory(memory_scope="Process", process_model=self.process_model, content="owner's secret")
		frappe.db.set_value("AI Memory", m.name, "expires_on", now_datetime())
		frappe.set_user(self.stranger)
		with self.assertRaises(frappe.PermissionError):
			memory_api.restore_memory(m.name)

	def test_owner_of_own_personal_memory_can_read_it(self):
		m = _memory(memory_scope="Agent", agent_element="Activity_personal",
					content="my own note", user=self.stranger)
		frappe.set_user(self.stranger)
		data = memory_api.get_memory(m.name)
		self.assertEqual(data["name"], m.name)
