# Copyright (c) 2026, one-fm and contributors
"""The site update countdown: start, read mid-countdown, expiry, cancel, who may call what."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.api import site_update

NOW = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)


class TestSiteUpdateCountdown(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		frappe.cache.delete_value(site_update.CACHE_KEY)

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.cache.delete_value(site_update.CACHE_KEY)

	def _at(self, moment):
		return patch.object(site_update, "_now", return_value=moment)

	def test_start_defaults_to_ten_minutes_and_publishes_to_all_users(self):
		with self._at(NOW), patch.object(frappe, "publish_realtime") as publish:
			result = site_update.start_site_update_countdown()

		self.assertEqual(result, {"ends_at": "2026-01-01T12:10:00Z", "seconds_remaining": 600})
		publish.assert_called_once()
		args, kwargs = publish.call_args
		self.assertEqual(args[0], "site_update_countdown")
		self.assertEqual(args[1], result)
		self.assertNotIn("user", kwargs)

	def test_get_reports_the_remaining_time_mid_countdown(self):
		with self._at(NOW), patch.object(frappe, "publish_realtime"):
			site_update.start_site_update_countdown(minutes=10)
		with self._at(NOW + timedelta(seconds=125)):
			state = site_update.get_site_update_countdown()

		self.assertEqual(state, {"active": True, "ends_at": "2026-01-01T12:10:00Z", "seconds_remaining": 475})

	def test_get_is_inactive_when_nothing_was_started(self):
		self.assertEqual(
			site_update.get_site_update_countdown(),
			{"active": False, "ends_at": None, "seconds_remaining": 0},
		)

	def test_get_is_inactive_once_the_end_time_has_passed(self):
		with self._at(NOW), patch.object(frappe, "publish_realtime"):
			site_update.start_site_update_countdown(minutes=1)
		with self._at(NOW + timedelta(minutes=1, seconds=1)):
			state = site_update.get_site_update_countdown()

		self.assertEqual(state, {"active": False, "ends_at": None, "seconds_remaining": 0})
		self.assertFalse(frappe.cache.get_value(site_update.CACHE_KEY))

	def test_cancel_clears_the_state_and_publishes_cancelled(self):
		with self._at(NOW), patch.object(frappe, "publish_realtime"):
			site_update.start_site_update_countdown()
		with patch.object(frappe, "publish_realtime") as publish:
			site_update.cancel_site_update_countdown()

		publish.assert_called_once()
		self.assertEqual(publish.call_args.args[:2], ("site_update_countdown", {"cancelled": True}))
		with self._at(NOW):
			self.assertFalse(site_update.get_site_update_countdown()["active"])

	def test_start_and_cancel_are_for_system_manager_only(self):
		frappe.set_user("Guest")  # Administrator always passes only_for, so use a user without the role
		with patch.object(frappe, "publish_realtime") as publish:
			with self.assertRaises(frappe.PermissionError):
				site_update.start_site_update_countdown()
			with self.assertRaises(frappe.PermissionError):
				site_update.cancel_site_update_countdown()
		publish.assert_not_called()
		self.assertFalse(frappe.cache.get_value(site_update.CACHE_KEY))

	def test_get_refuses_guests(self):
		frappe.set_user("Guest")
		with self.assertRaises(frappe.PermissionError):
			site_update.get_site_update_countdown()

	def test_bad_minutes_are_refused(self):
		with patch.object(frappe, "publish_realtime") as publish:
			for bad in (0, -5, "abc", None, site_update.MAX_MINUTES + 1):
				with self.subTest(minutes=bad), self.assertRaises(frappe.ValidationError):
					site_update.start_site_update_countdown(minutes=bad)
		publish.assert_not_called()

	def test_methods_are_whitelisted(self):
		for method in (
			site_update.start_site_update_countdown,
			site_update.get_site_update_countdown,
			site_update.cancel_site_update_countdown,
		):
			self.assertIn(method, frappe.whitelisted)
