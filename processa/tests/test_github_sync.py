# Copyright (c) 2026, one-fm and contributors
"""org_repos, which frappe_agile's repo-picker sync calls with the GitHub token on Processa Settings."""

from __future__ import annotations

import importlib
from unittest.mock import MagicMock, patch

from frappe.tests.utils import FrappeTestCase

from processa.agents_sandbox.customization import github_sync as logic


def _page(items, status=200):
	resp = MagicMock(status_code=status, text="x")
	resp.json = MagicMock(return_value=items)
	return resp


class TestOrgRepos(FrappeTestCase):
	def test_single_page_is_returned_as_name_description_url(self):
		items = [
			{"name": "processa", "description": "BPMN engine", "html_url": "https://github.com/ONE-F-M/processa"},
			{"name": "frappe_agile", "description": None, "html_url": "https://github.com/ONE-F-M/frappe_agile"},
		]
		with patch("requests.request", return_value=_page(items)) as mock_request:
			repos = logic.org_repos("gh-token", "ONE-F-M")
		self.assertEqual(len(repos), 2)
		self.assertEqual(repos[0], {"name": "processa", "description": "BPMN engine", "html_url": "https://github.com/ONE-F-M/processa"})
		# None description normalised to "", never carried through as null.
		self.assertEqual(repos[1]["description"], "")
		mock_request.assert_called_once()
		_args, kwargs = mock_request.call_args
		self.assertIn("Bearer gh-token", kwargs["headers"]["Authorization"])

	def test_pagination_stops_at_a_short_page(self):
		full_page = [{"name": f"repo{i}", "description": "", "html_url": "u"} for i in range(100)]
		short_page = [{"name": "last-one", "description": "", "html_url": "u"}]
		with patch("requests.request", side_effect=[_page(full_page), _page(short_page)]) as mock_request:
			repos = logic.org_repos("gh-token", "ONE-F-M")
		self.assertEqual(len(repos), 101)
		self.assertEqual(mock_request.call_count, 2)

	def test_empty_page_ends_pagination_immediately(self):
		with patch("requests.request", return_value=_page([])) as mock_request:
			repos = logic.org_repos("gh-token", "ONE-F-M")
		self.assertEqual(repos, [])
		mock_request.assert_called_once()

	def test_processa_has_no_repo_list_endpoint_of_its_own(self):
		with self.assertRaises(ImportError):
			importlib.import_module("processa.api.github_sync")
