# Tests for the AI Memory volume alert: thresholds come from settings, the
# crossing check is a pure function, and a crossing produces an in-app alert.

from __future__ import annotations

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.agents.memory import tools as T
from one_bpmn.agents.memory import volume_alert as V


class TestVolumeAlert(FrappeTestCase):
	def test_defaults_come_from_the_ranking_code(self):
		with patch("frappe.db.get_single_value", return_value=None):
			self.assertEqual(V.thresholds(), (T.REVISIT_SCOPE_ROWS, T.REVISIT_TOTAL_ROWS))

	def test_settings_override_defaults(self):
		frappe.db.set_single_value("Processa Settings", "memory_scope_row_alert", 7)
		frappe.db.set_single_value("Processa Settings", "memory_total_row_alert", 9)
		self.assertEqual(V.thresholds(), (7, 9))

	def test_crossed_is_quiet_below_and_names_the_scope_above(self):
		counts = {"total": 5, "largest": {"memory_scope": "Agent", "agent_element": "A1", "n": 3}}
		self.assertEqual(V.crossed(counts, 10, 100), [])
		lines = V.crossed(counts, 2, 100)
		self.assertEqual(len(lines), 1)
		self.assertIn("agent_element=A1", lines[0])
		self.assertEqual(len(V.crossed(counts, 2, 4)), 2)

	def test_crossing_sends_an_in_app_alert(self):
		agent = f"V_{frappe.generate_hash(length=8)}"
		T.memory_write("Agent", agent, "one", ignore_permissions=True)
		T.memory_write("Agent", agent, "two", ignore_permissions=True)
		frappe.db.set_single_value("Processa Settings", "memory_scope_row_alert", 1)
		# One recipient, not every System Manager on a production-sized user table.
		with patch.object(V, "_send_email"), patch.object(V, "_recipients", return_value=["Administrator"]):
			lines = V.check_volume()
		self.assertTrue(lines)
		note = frappe.get_all(
			"Notification Log",
			filters={"for_user": "Administrator", "document_type": "Processa Settings"},
			fields=["subject"],
			order_by="creation desc",
			limit=1,
		)
		self.assertTrue(note and "outgrown" in note[0]["subject"])

	def test_below_threshold_sends_nothing(self):
		with patch.object(V, "measure", return_value={"total": 1, "largest": {"memory_scope": "Agent", "n": 1}}), patch.object(
			V, "_notify"
		) as notify:
			self.assertEqual(V.check_volume(), [])
			notify.assert_not_called()


class TestThresholdsAreNeverZero(FrappeTestCase):
	"""A threshold of 0 is crossed by the first memory ever written, so it would
	fire on every site every night. A number field added to an existing Single
	reads back as 0 until somebody chooses a value, which is that exact state."""

	def _with(self, stored):
		with patch("frappe.db.get_single_value", return_value=stored):
			return V.thresholds()

	def test_zero_blank_and_missing_all_fall_back(self):
		for stored in (0, "0", "", None):
			self.assertEqual(self._with(stored), (T.REVISIT_SCOPE_ROWS, T.REVISIT_TOTAL_ROWS), stored)

	def test_a_chosen_value_is_kept(self):
		self.assertEqual(self._with(25), (25, 25))

	def test_unreadable_settings_still_give_a_usable_threshold(self):
		with patch("frappe.db.get_single_value", side_effect=RuntimeError("no settings")):
			self.assertEqual(V.thresholds(), (T.REVISIT_SCOPE_ROWS, T.REVISIT_TOTAL_ROWS))
