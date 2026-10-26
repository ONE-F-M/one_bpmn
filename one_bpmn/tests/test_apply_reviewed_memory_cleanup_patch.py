# Copyright (c) 2026, one-fm and contributors

import csv
import json
from collections import Counter
from unittest.mock import patch as mock_patch

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, now_datetime

from one_bpmn.agents.memory.prune import _invalidate
from one_bpmn.one_bpmn.patches.v1_0 import apply_reviewed_memory_cleanup as patch

SKILL = "zz-memory-cleanup-skill"
SKILL_BODY = "# Script rules\n\nUse result.\n"
SKILL_FIELDS = {"skill_name": SKILL, "status": "Draft", "description": "Test skill.", "tier": "Draft-Only"}
BLOCK = "## Printing\nPrint reaches the console only.\n"


def _memory(**kw):
	fields = {"doctype": "AI Memory", "memory_scope": "Agent", "agent_element": "run_prosally_agent", "content": "A fact."}
	doc = frappe.get_doc({**fields, **kw})
	doc.insert(ignore_permissions=True)
	return doc.name


class TestApplyReviewedMemoryCleanupPatch(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self.dir = frappe.get_site_path("private", "files")
		if frappe.db.exists("AI Skill", SKILL):
			frappe.db.set_value("AI Skill", SKILL, {**SKILL_FIELDS, "body": SKILL_BODY})
		else:
			frappe.get_doc({"doctype": "AI Skill", "name": SKILL, **SKILL_FIELDS, "body": SKILL_BODY}).db_insert()

	def _run(self, actions: dict, skill_rules: dict | None = None) -> Counter:
		path = f"{self.dir}/memory_actions_{frappe.generate_hash(length=6)}.csv"
		with open(path, "w", newline="") as f:
			writer = csv.writer(f)
			writer.writerow(["name", "action", "set_user"])
			for name, (action, user) in actions.items():
				writer.writerow([name, action, user])
		rules = skill_rules if skill_rules is not None else {}
		with mock_patch.object(patch, "ACTIONS_CSV", path), mock_patch.dict(patch.SKILL_RULES, rules):
			return patch.execute()

	def test_each_action_is_applied(self):
		delete, retire, user, shared, skill = (_memory(content=f"fact {i}") for i in range(5))
		sub = _memory(agent_element="write_script")
		counts = self._run(
			{
				delete: ("DELETE", ""),
				retire: ("RETIRE", ""),
				user: ("USER", "Administrator"),
				shared: ("SHARED", ""),
				sub: ("USER", "Administrator"),
				skill: ("SKILL", ""),
			},
			{skill: (("AI Skill", SKILL, "body"), None, BLOCK)},
		)
		self.assertFalse(frappe.db.exists("AI Memory", delete))
		self.assertTrue(frappe.db.get_value("AI Memory", retire, "expires_on"))
		retired = json.loads(frappe.db.get_value("AI Memory", retire, "metadata"))
		self.assertEqual(retired["pruned"]["reason"], patch.RETIRE_REASON)
		self.assertEqual(frappe.db.get_value("AI Memory", user, "user"), "Administrator")
		self.assertEqual(frappe.db.get_value("AI Memory", shared, "user_directed"), 1)
		self.assertEqual(json.loads(frappe.db.get_value("AI Memory", shared, "metadata"))["reviewed"], "reviewed 13 Oct")
		self.assertEqual(frappe.db.get_value("AI Memory", sub, "agent_element"), "run_logix_agent")
		self.assertFalse(frappe.db.exists("AI Memory", skill))
		self.assertIn("Print reaches the console only.", frappe.db.get_value("AI Skill", SKILL, "body"))
		self.assertEqual(dict(counts), {"DELETE": 1, "RETIRE": 1, "USER": 2, "SHARED": 1, "SKILL": 1})

	def test_a_missing_name_is_skipped_and_a_rerun_changes_nothing(self):
		retire = _memory()
		actions = {retire: ("RETIRE", ""), "gone000000": ("DELETE", "")}
		self._run(actions)
		first = frappe.db.get_value("AI Memory", retire, "expires_on")
		counts = self._run(actions)
		self.assertEqual(counts["DELETE missing"], 1)
		self.assertEqual(counts["RETIRE already expired"], 1)
		self.assertEqual(frappe.db.get_value("AI Memory", retire, "expires_on"), first)

	def test_a_skill_row_stays_when_its_rule_is_not_in_the_target(self):
		skill = _memory()
		counts = self._run(
			{skill: ("SKILL", "")},
			{skill: (("AI Skill", SKILL, "body"), "text that is not there", None)},
		)
		self.assertEqual(counts["SKILL rule not found"], 1)
		self.assertTrue(frappe.db.exists("AI Memory", skill))

	def test_a_kept_row_that_had_expired_becomes_active(self):
		user = _memory()
		_invalidate(user, "decayed", now_datetime())
		self._run({user: ("USER", "Administrator")})
		self.assertFalse(frappe.db.get_value("AI Memory", user, "expires_on"))
		self.assertNotIn("pruned", json.loads(frappe.db.get_value("AI Memory", user, "metadata") or "{}"))

	def test_retired_rows_are_deleted_only_after_thirty_days_and_unless_asked_back(self):
		old, new, asked_back = _memory(), _memory(), _memory()
		_invalidate(old, patch.RETIRE_REASON, add_days(now_datetime(), -31))
		_invalidate(new, patch.RETIRE_REASON, now_datetime())
		_invalidate(asked_back, patch.RETIRE_REASON, add_days(now_datetime(), -31))
		frappe.db.set_value("AI Memory", asked_back, "expires_on", None)
		patch.delete_retired_memories()
		self.assertFalse(frappe.db.exists("AI Memory", old))
		self.assertTrue(frappe.db.exists("AI Memory", new))
		self.assertTrue(frappe.db.exists("AI Memory", asked_back))

	def test_the_shipped_list_matches_the_reviewed_counts(self):
		actions = patch._read_actions()
		self.assertEqual(
			dict(Counter(row["action"] for row in actions.values())),
			{"DELETE": 1187, "RETIRE": 311, "USER": 163, "SHARED": 11, "SKILL": 23},
		)
		self.assertEqual(set(patch._names(actions, "SKILL")), set(patch.SKILL_RULES))
		self.assertTrue(all(row["set_user"] for row in actions.values() if row["action"] == "USER"))
