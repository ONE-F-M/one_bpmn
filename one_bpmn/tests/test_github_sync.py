# Copyright (c) 2026, one-fm and contributors
"""list_org_repos — the cross-app entry point frappe_agile's own repo-picker
sync calls (Work Item's target_app Link field has no GitHub credential of
its own, so it reuses the one already configured for the Dev Agent sandbox
on Processa Settings, rather than a second token existing purely to
duplicate it).
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from frappe.tests.utils import FrappeTestCase

from one_bpmn.api import github_sync


def _page(items, status=200):
	resp = MagicMock(status_code=status, text="x")
	resp.json = MagicMock(return_value=items)
	return resp


class TestListOrgRepos(FrappeTestCase):
	def test_single_page_is_returned_as_name_description_url(self):
		items = [
			{"name": "one_bpmn", "description": "BPMN engine", "html_url": "https://github.com/ONE-F-M/one_bpmn"},
			{"name": "frappe_agile", "description": None, "html_url": "https://github.com/ONE-F-M/frappe_agile"},
		]
		with patch("requests.request", return_value=_page(items)) as mock_request:
			repos = github_sync._list_org_repos("gh-token", "ONE-F-M")
		self.assertEqual(len(repos), 2)
		self.assertEqual(repos[0], {"name": "one_bpmn", "description": "BPMN engine", "html_url": "https://github.com/ONE-F-M/one_bpmn"})
		# None description normalised to "", never carried through as null.
		self.assertEqual(repos[1]["description"], "")
		mock_request.assert_called_once()
		_args, kwargs = mock_request.call_args
		self.assertIn("Bearer gh-token", kwargs["headers"]["Authorization"])

	def test_pagination_stops_at_a_short_page(self):
		full_page = [{"name": f"repo{i}", "description": "", "html_url": "u"} for i in range(100)]
		short_page = [{"name": "last-one", "description": "", "html_url": "u"}]
		with patch("requests.request", side_effect=[_page(full_page), _page(short_page)]) as mock_request:
			repos = github_sync._list_org_repos("gh-token", "ONE-F-M")
		self.assertEqual(len(repos), 101)
		self.assertEqual(mock_request.call_count, 2)

	def test_empty_page_ends_pagination_immediately(self):
		with patch("requests.request", return_value=_page([])) as mock_request:
			repos = github_sync._list_org_repos("gh-token", "ONE-F-M")
		self.assertEqual(repos, [])
		mock_request.assert_called_once()

	def test_list_org_repos_resolves_the_token_from_processa_settings(self):
		mock_settings = SimpleNamespace(get_password=lambda *a, **k: "settings-token")
		with patch.object(github_sync.frappe, "get_cached_doc", return_value=mock_settings), patch.object(
			github_sync, "_list_org_repos", return_value=[{"name": "one_bpmn", "description": "", "html_url": "u"}]
		) as mock_list:
			result = github_sync.list_org_repos(org="ONE-F-M")
		mock_list.assert_called_once_with("settings-token", "ONE-F-M")
		self.assertEqual(result[0]["name"], "one_bpmn")

	def test_missing_token_is_refused_before_any_call(self):
		mock_settings = SimpleNamespace(get_password=lambda *a, **k: "")
		with patch.object(github_sync.frappe, "get_cached_doc", return_value=mock_settings), patch(
			"requests.request"
		) as mock_request:
			with self.assertRaises(Exception):
				github_sync.list_org_repos()
		mock_request.assert_not_called()
