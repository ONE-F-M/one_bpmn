# Copyright (c) 2026, one-fm and contributors
# Search-bar style matching on the Process Instance list.

from __future__ import annotations

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.api import instance_api
from one_bpmn.api.instance_api import _search_rank, list_process_instances

test_ignore = ["BPMN Process Model"]

SD5 = "Software Development v5"
FLR = "First Line Response Leave Approval"


class TestSearchRank(FrappeTestCase):
	def rank(self, query, model=SD5):
		return _search_rank(query, {"process_model": model, "name": "BPMN-INST-0001"})

	def test_acronym_with_and_without_spaces(self):
		self.assertEqual(self.rank("SD5"), 2)
		self.assertEqual(self.rank("S D 5"), 2)

	def test_substring_ranks_best(self):
		self.assertEqual(self.rank("software dev"), 0)

	def test_token_prefixes(self):
		self.assertEqual(self.rank("dev soft"), 1)

	def test_spaced_acronym_tokens(self):
		self.assertEqual(self.rank("flr L A", FLR), 2)
		self.assertEqual(self.rank("f l r l a", FLR), 1)
		self.assertEqual(self.rank("flrla", FLR), 2)

	def test_no_match(self):
		self.assertIsNone(self.rank("zzz"))
		self.assertIsNone(self.rank("SD6"))

	def test_single_char_only_substring(self):
		self.assertIsNone(self.rank("q"))


class TestListSearch(FrappeTestCase):
	def _instance(self, model: str, status: str = "Active") -> str:
		doc = frappe.get_doc(
			{"doctype": "BPMN Process Instance", "process_model": model, "status": status}
		)
		doc.flags.ignore_links = True
		doc.insert(ignore_permissions=True, ignore_mandatory=True)
		return doc.name

	def test_search_ranks_and_filters(self):
		sd5 = self._instance(SD5)
		other = self._instance("Procurement v1")
		names = [d.name for d in list_process_instances(search="S D 5", limit_page_length=500)]
		self.assertIn(sd5, names)
		self.assertNotIn(other, names)

	def test_search_combines_with_filters(self):
		done = self._instance(SD5, status="Completed")
		names = [
			d.name
			for d in list_process_instances(
				filters={"status": "Active"}, search="SD5", limit_page_length=500
			)
		]
		self.assertNotIn(done, names)

	def test_no_match_returns_empty(self):
		self._instance(SD5)
		self.assertEqual(list_process_instances(search="qqqzzz"), [])

	def test_search_never_loads_unrelated_rows(self):
		sd5 = self._instance(SD5)
		other = self._instance("Procurement v1")
		with patch.object(instance_api, "_search_rank", wraps=_search_rank) as rank:
			names = [d.name for d in list_process_instances(search="SD5", limit_page_length=500)]
		ranked = {call.args[1].get("name") for call in rank.call_args_list}
		self.assertIn(sd5, names)
		self.assertNotIn(other, ranked)
