# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""WI-001637 live-link amendment: config authoritative at dispatch + write-back."""

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.agents.agent_config_resolver import (
	_refuse_roles_the_editor_does_not_hold,
	config_static_context,
	grantable_roles,
	resolve_dispatch_overrides,
	update_agent_config_from_shape,
)

TEST_CONFIG = "ZZ Live Link Test Agent"


class TestAgentConfigLiveLink(FrappeTestCase):
	def setUp(self):
		super().setUp()
		if not frappe.db.exists("AI Agent Configuration", TEST_CONFIG):
			frappe.get_doc({
				"doctype": "AI Agent Configuration",
				"agent_name": TEST_CONFIG,
				"agent_id": "zz_live_link_test_agent",
				"agent_framework": "Direct API",
				"agent_type": "Background",
				# Every agent type now walks the Agent Creation Process,
				# whose start condition is lifecycle_status == "Draft". This fixture
				# is a settled agent, not one being created — inserting it Live keeps
				# the process out of it, which matters because that process ASSESSES
				# and REWRITES a thin system prompt, and this test asserts on the
				# prompt's exact value.
				"lifecycle_status": "Live",
				"system_prompt": "Original prompt.",
				"temperature": 0.5,
				"max_tokens": 512,
			}).insert(ignore_permissions=True)

	def test_dispatch_overrides_return_live_values(self):
		overrides = resolve_dispatch_overrides(TEST_CONFIG)
		self.assertEqual(overrides.get("aiSystemPrompt"), "Original prompt.")
		self.assertEqual(overrides.get("aiTemperature"), 0.5)
		self.assertEqual(overrides.get("aiMaxTokens"), 512)

	def test_dispatch_overrides_missing_config_falls_back_empty(self):
		self.assertEqual(resolve_dispatch_overrides("No Such Config 404"), {})
		self.assertEqual(resolve_dispatch_overrides(""), {})

	def test_dispatch_merge_prefers_config_over_shape(self):
		# The dispatchers overlay overrides onto the shape's copies.
		task_cfg = {"aiSystemPrompt": "stale shape copy", "aiOutputVariable": "out"}
		merged = {**task_cfg, **resolve_dispatch_overrides(TEST_CONFIG)}
		self.assertEqual(merged["aiSystemPrompt"], "Original prompt.")
		# Shape-only fields survive untouched.
		self.assertEqual(merged["aiOutputVariable"], "out")

	def test_write_back_updates_config(self):
		result = update_agent_config_from_shape(
			TEST_CONFIG,
			{"aiSystemPrompt": "Edited from the dialog.", "aiTemperature": "0.9"},
		)
		self.assertTrue(result["ok"])
		self.assertIn("system_prompt", result["updated"])
		self.assertIn("temperature", result["updated"])
		# Not Live -> no re-provision.
		self.assertFalse(result["reprovisioned"])
		self.assertEqual(
			frappe.db.get_value("AI Agent Configuration", TEST_CONFIG, "system_prompt"),
			"Edited from the dialog.",
		)

	def test_write_back_no_change_is_noop(self):
		prompt = frappe.db.get_value("AI Agent Configuration", TEST_CONFIG, "system_prompt")
		result = update_agent_config_from_shape(TEST_CONFIG, {"aiSystemPrompt": prompt})
		self.assertEqual(result["updated"], [])
		self.assertFalse(result["reprovisioned"])

	def test_write_back_ignores_unknown_fields(self):
		# WI-001655 inverted the old rule: aiModel IS the updatable pick now,
		# while aiProvider (derived from the model) and shape-only fields are
		# ignored. An invalid model name fails link validation on save.
		result = update_agent_config_from_shape(
			TEST_CONFIG, {"aiProvider": "Claude", "aiOutputVariable": "x"}
		)
		self.assertEqual(result["updated"], [])

	def test_write_back_requires_write_permission(self):
		self.set_user("Guest")
		try:
			with self.assertRaises(frappe.PermissionError):
				update_agent_config_from_shape(TEST_CONFIG, {"aiSystemPrompt": "hacked"})
		finally:
			self.set_user("Administrator")


class TestTheModalCanEditWhatTheAgentMayDo(FrappeTestCase):
	"""WI-002054: the roles an agent holds are editable from the editor modal.

	They were only on the desk form, which is not where anyone configures an
	agent — so "may this agent move a work item to Done" had no answer in the
	place the question gets asked.
	"""

	def setUp(self):
		super().setUp()
		if not frappe.db.exists("AI Agent Configuration", TEST_CONFIG):
			frappe.get_doc({
				"doctype": "AI Agent Configuration",
				"agent_name": TEST_CONFIG,
				"agent_id": "zz_live_link_test_agent",
				"agent_framework": "Direct API",
				"agent_type": "Background",
				"lifecycle_status": "Live",
				"system_prompt": "Original prompt.",
			}).insert(ignore_permissions=True)

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.rollback()
		super().tearDown()

	# ── reading ──────────────────────────────────────────────────────────

	def test_the_roles_come_back_for_the_modal(self):
		update_agent_config_from_shape(TEST_CONFIG, {"aiAgentRoles": [{"role": "Process Owner"}]})
		self.assertEqual(
			config_static_context(TEST_CONFIG)["aiAgentRoles"], [{"role": "Process Owner"}]
		)

	def test_every_editable_table_comes_back(self):
		"""The modal replaces each table WHOLE, so a table it is not given opens
		empty and is saved back empty. Skills were missing from this answer."""
		keys = set(config_static_context(TEST_CONFIG))
		self.assertIn("aiSkills", keys)
		self.assertIn("aiAgentRoles", keys)
		self.assertIn("aiExamples", keys)
		self.assertIn("aiGuardrails", keys)

	def test_asking_about_no_agent_answers_instead_of_crashing(self):
		"""It named a variable that does not exist in that branch and raised
		NameError — so opening the modal before picking an agent broke it."""
		self.assertEqual(
			config_static_context(""),
			{"aiExamples": [], "aiGuardrails": [], "aiSkills": [], "aiAgentRoles": []},
		)

	# ── writing ──────────────────────────────────────────────────────────

	def test_granting_a_role_grants_it(self):
		result = update_agent_config_from_shape(
			TEST_CONFIG, {"aiAgentRoles": [{"role": "Process Owner"}]}
		)
		self.assertIn("agent_roles", result["updated"])
		self.assertEqual(
			frappe.get_all("AI Agent Allowed Role", filters={"parent": TEST_CONFIG}, pluck="role"),
			["Process Owner"],
		)

	def test_removing_a_role_revokes_it(self):
		update_agent_config_from_shape(TEST_CONFIG, {"aiAgentRoles": [{"role": "Process Owner"}]})
		update_agent_config_from_shape(TEST_CONFIG, {"aiAgentRoles": []})
		self.assertEqual(
			frappe.get_all("AI Agent Allowed Role", filters={"parent": TEST_CONFIG}, pluck="role"),
			[],
		)

	def test_the_same_role_twice_is_one_grant(self):
		update_agent_config_from_shape(
			TEST_CONFIG,
			{"aiAgentRoles": [{"role": "Process Owner"}, {"role": "Process Owner"}]},
		)
		self.assertEqual(
			frappe.get_all("AI Agent Allowed Role", filters={"parent": TEST_CONFIG}, pluck="role"),
			["Process Owner"],
		)

	def test_a_role_that_does_not_exist_is_dropped(self):
		update_agent_config_from_shape(
			TEST_CONFIG, {"aiAgentRoles": [{"role": "No Such Role 404"}]}
		)
		self.assertEqual(
			frappe.get_all("AI Agent Allowed Role", filters={"parent": TEST_CONFIG}, pluck="role"),
			[],
		)

	def test_not_sending_the_table_leaves_it_alone(self):
		update_agent_config_from_shape(TEST_CONFIG, {"aiAgentRoles": [{"role": "Process Owner"}]})
		update_agent_config_from_shape(TEST_CONFIG, {"aiSystemPrompt": "Something else."})
		self.assertEqual(
			frappe.get_all("AI Agent Allowed Role", filters={"parent": TEST_CONFIG}, pluck="role"),
			["Process Owner"],
		)

	# ── the escalation guard ─────────────────────────────────────────────
	#
	# Exercised against the guard itself rather than through the endpoint,
	# because the endpoint cannot reach it on a stock site: the only role with
	# write on AI Agent Configuration is System Manager, and a System Manager
	# may grant anything. The guard is what makes widening that safe — the
	# moment a site lets a non-manager edit agents, it is the only thing
	# standing between "can edit an agent" and "can obtain any permission".

	def test_only_a_system_manager_can_edit_an_agent_today(self):
		"""Pinning why the guard looks dormant. If this ever fails because
		another role gained write, the guard has started doing real work and the
		tests below are the ones that describe it."""
		can_write = frappe.get_all(
			"DocPerm",
			filters={"parent": "AI Agent Configuration", "write": 1},
			pluck="role",
		)
		self.assertEqual(can_write, ["System Manager"])

	def test_you_cannot_grant_a_role_you_do_not_hold(self):
		"""An agent acts with what it is given. Without this, editing an agent is
		a way to obtain any permission on the site: grant it System Manager, then
		ask it to do the thing you could not."""
		frappe.set_user(_a_user_holding("Process Owner"))
		with self.assertRaises(frappe.PermissionError):
			_refuse_roles_the_editor_does_not_hold([{"role": "System Manager"}], [])

	def test_you_can_grant_a_role_you_do_hold(self):
		frappe.set_user(_a_user_holding("Process Owner"))
		# No exception is the assertion.
		_refuse_roles_the_editor_does_not_hold([{"role": "Process Owner"}], [])

	def test_a_role_the_agent_already_holds_survives_an_unrelated_save(self):
		"""Judged on what CHANGED. An agent may legitimately hold a role its
		editor does not, and editing the prompt should not fail because of it."""
		frappe.set_user(_a_user_holding("Process Owner"))
		_refuse_roles_the_editor_does_not_hold(
			[{"role": "System Manager"}], [{"role": "System Manager"}]
		)

	def test_the_picker_offers_only_what_can_be_saved(self):
		"""An option that cannot be saved should never be offered, so the picker
		and the guard read the same list."""
		frappe.set_user(_a_user_holding("Process Owner"))
		self.assertEqual(grantable_roles(), ["Process Owner"])

	def test_a_system_manager_may_grant_anything(self):
		"""Not a loophole: they already hold every permission the grant could
		confer, and they are who Frappe entrusts with role administration."""
		self.assertIn("System Manager", grantable_roles())
		self.assertGreater(len(grantable_roles()), 1)


def _a_user_holding(role: str) -> str:
	"""A person who holds exactly one role, made here rather than borrowed, so
	the test still means something on a site where everyone is a manager."""
	email = f"_test_grantor_{frappe.scrub(role)}@example.com"
	if not frappe.db.exists("User", email):
		user = frappe.new_doc("User")
		user.update({"email": email, "first_name": "Grantor", "send_welcome_email": 0})
		user.append("roles", {"role": role})
		user.flags.ignore_permissions = True
		user.insert(ignore_permissions=True)
	return email
