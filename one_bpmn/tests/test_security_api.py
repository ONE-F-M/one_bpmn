# Copyright (c) 2026, one-fm and contributors
# The Processa Security view's API.
#
# Two properties matter more than the rest and are tested hardest. Raw screened
# content must never come back — it is not stored, and the reader is written so
# that stays true even if the doctype grows a field. And this module must stay a
# window: every write delegates to the module that owns the behaviour, so there
# is one implementation of the security rules to audit rather than two that can
# disagree.

from __future__ import annotations

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.api import security_api as S

PREFIX = "ZZ SecAPI"


class TestSecurityApi(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self._cleanup()
		self.agent = frappe.get_doc({
			"doctype": "AI Agent Configuration",
			"agent_name": f"{PREFIX} agent",
			"agent_id": "zz_secapi_agent",
			"agent_type": "Chat",
			"agent_framework": "Direct API",
			"chat_mode_label": f"{PREFIX}",
			"enabled": 1,
		}).insert(ignore_permissions=True).name

	def tearDown(self):
		self._cleanup()
		frappe.db.commit()

	def _cleanup(self):
		frappe.db.delete("AI Security Event", {"conversation": ("like", f"{PREFIX}%")})
		frappe.db.delete("AI Conversation Lock", {"conversation": ("like", f"{PREFIX}%")})
		frappe.db.delete("AI Agent Configuration", {"agent_name": ("like", f"{PREFIX}%")})

	def _event(self, **kw):
		values = {
			"doctype": "AI Security Event",
			"boundary": "input",
			"stage": "injection",
			"action": "Flag",
			"severity": "High",
			"agent_configuration": self.agent,
			"conversation": f"{PREFIX}-conv",
			"content_hash": "abc123",
			"content_length": 42,
			"detail": "matched a rule",
		}
		values.update(kw)
		return frappe.get_doc(values).insert(ignore_permissions=True).name

	# ------------------------------------------------------------------
	# AC 1 — the stream, filtered and paged
	# ------------------------------------------------------------------
	def test_events_come_back_newest_first(self):
		first = self._event(detail="older")
		second = self._event(detail="newer")
		names = [e["name"] for e in S.list_events(agent=self.agent)["events"]]
		self.assertEqual(names[:2], [second, first])

	def test_filters_narrow_the_stream(self):
		self._event(action="Flag", boundary="input")
		blocked = self._event(action="Block", boundary="output")

		by_action = S.list_events(agent=self.agent, action="Block")
		self.assertEqual([e["name"] for e in by_action["events"]], [blocked])
		by_boundary = S.list_events(agent=self.agent, boundary="output")
		self.assertEqual([e["name"] for e in by_boundary["events"]], [blocked])

	def test_paging_reports_the_whole_size_not_the_page(self):
		"""A console that silently truncates is worse than one that says
		"50 of 4,312" — the total is what tells a reviewer to filter."""
		for i in range(3):
			self._event(detail=f"e{i}")

		page = S.list_events(agent=self.agent, page_length=2)

		self.assertEqual(len(page["events"]), 2)
		self.assertEqual(page["total"], 3)
		second = S.list_events(agent=self.agent, page_length=2, start=2)
		self.assertEqual(len(second["events"]), 1)

	def test_page_length_is_capped(self):
		"""An unbounded page_length is a way to pull the whole log in one request."""
		self.assertEqual(S.list_events(page_length=100000)["page_length"], 200)

	# ------------------------------------------------------------------
	# AC 2 — everything recorded, and nothing that was not
	# ------------------------------------------------------------------
	def test_an_event_opens_with_its_hash_and_no_raw_content(self):
		name = self._event()

		out = S.get_event(name)

		self.assertEqual(out["content_hash"], "abc123")
		self.assertEqual(out["content_length"], 42)
		self.assertFalse(out["content_stored"])
		for leaky in ("content", "text", "message", "raw", "prompt"):
			self.assertNotIn(leaky, out, f"{leaky} must never be returned — it is never stored")

	def test_the_reader_names_its_fields_rather_than_dumping_the_doc(self):
		"""So a field added to the doctype later cannot start leaking by default."""
		name = self._event()
		out = S.get_event(name)
		self.assertEqual(set(out) - {"content_stored", "promoted_case"}, set(S.EVENT_FIELDS))

	# ------------------------------------------------------------------
	# AC 3 — the pack is System-Manager-writable, readable by others
	# ------------------------------------------------------------------
	def test_pattern_writes_are_refused_without_the_role(self):
		with patch.object(S, "_can_edit_patterns", return_value=False):
			with self.assertRaises(frappe.PermissionError):
				S.save_pattern({"pattern_name": f"{PREFIX} rule", "pattern": "x"})
			with self.assertRaises(frappe.PermissionError):
				S.set_pattern_enabled("whatever", 0)

	def test_the_pack_reports_whether_this_user_may_edit_it(self):
		"""So the screen renders read-only without a second round trip."""
		out = S.list_patterns()
		self.assertIn("can_edit", out)
		self.assertIsInstance(out["patterns"], list)

	def test_pattern_options_come_from_the_doctype(self):
		"""Hand-copied option lists rot silently; these are read from the schema."""
		opts = S.pattern_options()
		meta = frappe.get_meta("AI Injection Pattern")
		self.assertEqual(
			opts["severity"], [o for o in (meta.get_field("severity").options or "").split("\n") if o]
		)
		self.assertIn("Block", opts["action"])

	# ------------------------------------------------------------------
	# AC 4 / AC 7 — writes delegate, they are not reimplemented
	# ------------------------------------------------------------------
	def test_release_delegates_to_the_owning_action(self):
		"""15.3 owns the reviewer rule, the note requirement and the refusal to
		self-release. A second copy here would be one more thing to keep in step."""
		with patch("one_bpmn.api.conversation_locks.release_lock", return_value={"ok": True}) as owner:
			S.release("ZZ-LOCK", notes="reviewed")

		owner.assert_called_once()
		self.assertEqual(owner.call_args.kwargs.get("notes"), "reviewed")

	def test_promote_delegates_and_reports_which_outcome(self):
		with patch(
			"one_bpmn.api.security_events.promote_to_eval_case",
			return_value={"eval_case": "CASE-1", "created": True, "suite": "SUITE-1"},
		) as owner:
			created = S.promote_event("EV-1")
		owner.assert_called_once()
		self.assertEqual(created, {"case": "CASE-1", "already_promoted": False, "suite": "SUITE-1"})

		with patch(
			"one_bpmn.api.security_events.promote_to_eval_case",
			return_value={"eval_case": "CASE-1", "created": False, "suite": "SUITE-1"},
		):
			again = S.promote_event("EV-1")
		self.assertTrue(
			again["already_promoted"],
			"clicking twice must be distinguishable from the first click failing",
		)

	def test_locks_come_back_with_their_release_audit(self):
		out = S.list_locks()
		self.assertIn("locks", out)
		self.assertEqual(out["me"], frappe.session.user)

	# ------------------------------------------------------------------
	# AC 5 — per-agent screening, built from the fields that exist
	# ------------------------------------------------------------------
	def test_screening_renders_only_fields_the_doctype_really_has(self):
		"""output_screening_mode is 15.1's and does not exist yet. A screen that
		assumed it would offer a control writing nowhere."""
		out = S.agent_screening(self.agent)

		names = [c["fieldname"] for c in out["controls"]]
		self.assertIn("pii_screening", names)
		meta = frappe.get_meta("AI Agent Configuration")
		for fieldname in names:
			self.assertIsNotNone(meta.get_field(fieldname))

	def test_a_control_carries_the_doctypes_own_label_and_options(self):
		control = next(c for c in S.agent_screening(self.agent)["controls"] if c["fieldname"] == "pii_screening")
		self.assertEqual(control["label"], "PII Input Screening")
		self.assertEqual(control["options"], ["Enabled", "Disabled"])
		self.assertTrue(control["description"])

	def test_saving_screening_writes_the_agent(self):
		S.save_agent_screening(self.agent, {"pii_screening": "Disabled"})
		self.assertEqual(
			frappe.db.get_value("AI Agent Configuration", self.agent, "pii_screening"), "Disabled"
		)

	def test_saving_screening_refuses_to_write_anything_else(self):
		"""This endpoint must never become a general writer for the whole agent —
		the rest of the configuration is edited where it always was."""
		before = frappe.db.get_value("AI Agent Configuration", self.agent, "system_prompt")

		# A value that really differs, so "updated" reflects the write rather than
		# a no-op — writing the same value back is correctly reported as no change.
		out = S.save_agent_screening(
			self.agent, {"pii_screening": "Disabled", "system_prompt": "OWNED", "enabled": 0}
		)

		self.assertEqual(out["updated"], ["pii_screening"])
		self.assertEqual(
			frappe.db.get_value("AI Agent Configuration", self.agent, "system_prompt"), before
		)
		self.assertEqual(frappe.db.get_value("AI Agent Configuration", self.agent, "enabled"), 1)

	def test_an_unknown_screening_field_is_ignored_not_created(self):
		out = S.save_agent_screening(self.agent, {"output_screening_mode": "Block"})
		self.assertEqual(out["updated"], [], "a field 15.1 has not added yet cannot be written")
