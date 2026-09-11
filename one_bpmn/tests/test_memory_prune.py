# Tests for nightly AI Memory pruning: each rule fires on its own, fresh and
# user-directed rows survive, and pruning is a soft delete with a reason.

from __future__ import annotations

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_to_date, now_datetime

from one_bpmn.agents.memory import prune as P
from one_bpmn.agents.memory import tools as T

CONFIG = {"min_confidence": 0.2, "uncorroborated_days": 180, "low_importance_days": 90}


class TestPruneReason(FrappeTestCase):
	NOW = now_datetime()

	def _row(self, **kw):
		row = {"modified": self.NOW, "confidence": 0.6, "corroboration_count": 0, "importance": 3, "user_directed": 0}
		row.update(kw)
		return row

	def test_fresh_row_survives(self):
		self.assertIsNone(P.prune_reason(self._row(), CONFIG, self.NOW))

	def test_decayed_confidence(self):
		self.assertEqual(P.prune_reason(self._row(confidence=0.1), CONFIG, self.NOW), "decayed")
		# 0.6 halves every 90 days: under 0.2 after about 143 days
		old = self._row(modified=add_to_date(self.NOW, days=-150))
		self.assertEqual(P.prune_reason(old, CONFIG, self.NOW), "decayed")

	def test_never_corroborated(self):
		# confidence kept high so the decay rule stays quiet and this rule decides
		old = self._row(modified=add_to_date(self.NOW, days=-200), confidence=1.0)
		self.assertEqual(P.prune_reason(old, CONFIG, self.NOW), "never corroborated")
		corroborated = dict(old, corroboration_count=2, last_corroborated=self.NOW)
		self.assertIsNone(P.prune_reason(corroborated, CONFIG, self.NOW))

	def test_irrelevant_minor_fact(self):
		old_minor = self._row(modified=add_to_date(self.NOW, days=-100), confidence=1.0, importance=1)
		self.assertEqual(P.prune_reason(old_minor, CONFIG, self.NOW), "irrelevant")
		old_normal = dict(old_minor, importance=3)
		self.assertIsNone(P.prune_reason(old_normal, CONFIG, self.NOW))

	def test_user_directed_is_never_pruned(self):
		row = self._row(modified=add_to_date(self.NOW, days=-400), confidence=0.05, importance=1, user_directed=1)
		self.assertIsNone(P.prune_reason(row, CONFIG, self.NOW))

	def test_zero_turns_a_rule_off(self):
		off = dict(CONFIG, min_confidence=0, uncorroborated_days=0, low_importance_days=0)
		row = self._row(modified=add_to_date(self.NOW, days=-400), confidence=0.05, importance=1)
		self.assertIsNone(P.prune_reason(row, off, self.NOW))


class TestPruneSweep(FrappeTestCase):
	def _backdate(self, name, days):
		frappe.db.set_value("AI Memory", name, "modified", add_to_date(now_datetime(), days=-days), update_modified=False)

	def test_sweep_soft_deletes_with_reason_and_keeps_the_rest(self):
		agent = f"PR_{frappe.generate_hash(length=8)}"
		stale = T.memory_write("Agent", agent, "old uncorroborated fact", ignore_permissions=True)
		self._backdate(stale["name"], 200)
		fresh = T.memory_write("Agent", agent, "fresh fact", ignore_permissions=True)
		kept = T.memory_write("Agent", agent, "remember this always", user_directed=True, ignore_permissions=True)
		self._backdate(kept["name"], 400)

		counts = P.prune_memories()

		self.assertGreaterEqual(counts["decayed"] + counts["never corroborated"], 1)
		row = frappe.db.get_value("AI Memory", stale["name"], ["expires_on", "metadata"], as_dict=True)
		self.assertIsNotNone(row.expires_on)
		self.assertIn((T._json_loads(row.metadata) or {}).get("pruned", {}).get("reason"), ("decayed", "never corroborated"))
		self.assertTrue(frappe.db.exists("AI Memory", stale["name"]))  # soft delete, row stays
		self.assertIsNone(frappe.db.get_value("AI Memory", fresh["name"], "expires_on"))
		self.assertIsNone(frappe.db.get_value("AI Memory", kept["name"], "expires_on"))
		# a retired memory no longer comes back from search
		self.assertNotIn(stale["name"], [r["name"] for r in T.memory_search("Agent", agent, "uncorroborated fact", ignore_permissions=True)])

	def test_second_sweep_finds_nothing(self):
		agent = f"PR_{frappe.generate_hash(length=8)}"
		stale = T.memory_write("Agent", agent, "old uncorroborated fact", ignore_permissions=True)
		self._backdate(stale["name"], 200)
		P.prune_memories()
		before = frappe.db.get_value("AI Memory", stale["name"], "expires_on")
		P.prune_memories()
		self.assertEqual(frappe.db.get_value("AI Memory", stale["name"], "expires_on"), before)

	def test_config_reads_settings(self):
		original = frappe.db.get_single_value("Processa Settings", "memory_prune_uncorroborated_days")
		self.addCleanup(frappe.db.set_single_value, "Processa Settings", "memory_prune_uncorroborated_days", original)
		frappe.db.set_single_value("Processa Settings", "memory_prune_uncorroborated_days", 7)
		self.assertEqual(P.prune_config()["uncorroborated_days"], 7)


class TestThresholdDefaults(FrappeTestCase):
	"""A number field added to an existing Single reads back as 0, and 0 switches
	every one of these rules off. That is how nightly pruning came to do nothing
	on a site where nobody had opened the settings."""

	def _with(self, stored):
		with patch("frappe.db.get_singles_dict", return_value=stored):
			return P.prune_config()

	def test_a_never_set_field_uses_the_code_default(self):
		"""get_singles_dict returns an empty string for a field nobody has ever
		written, and the old check was `is not None`, which an empty string
		passes. Every threshold then read as 0, and 0 is off."""
		for stored in ({}, {"memory_prune_min_confidence": ""}, {"memory_prune_min_confidence": None}):
			self.assertEqual(self._with(stored)["min_confidence"], P._DEFAULTS["min_confidence"], stored)

	def test_a_deliberate_zero_still_switches_a_rule_off(self):
		"""0 is the documented way to switch a rule off, so it is never treated
		as absent. A stored 0 that nobody chose is corrected by the
		seed_memory_setting_defaults patch, not guessed at here."""
		self.assertEqual(self._with({"memory_prune_min_confidence": 0})["min_confidence"], 0)

	def test_all_three_fall_back_together(self):
		config = self._with({})
		self.assertEqual(config, dict(P._DEFAULTS))

	def test_a_chosen_value_is_kept(self):
		config = self._with({"memory_prune_min_confidence": 0.45, "memory_prune_uncorroborated_days": 30})
		self.assertEqual(config["min_confidence"], 0.45)
		self.assertEqual(config["uncorroborated_days"], 30)

	def test_an_unreadable_settings_row_still_prunes(self):
		with patch("frappe.db.get_singles_dict", side_effect=RuntimeError("no settings")):
			self.assertEqual(P.prune_config(), dict(P._DEFAULTS))
