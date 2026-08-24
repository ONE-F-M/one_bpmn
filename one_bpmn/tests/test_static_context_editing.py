# Copyright (c) 2026, one-fm and contributors
# WI-001639: examples and guard rails — the agent's frozen static context —
# are editable from the Processa AI Agent Config modal, not only from the desk
# form or the assistant's create payload.
#
# Covers the read path the modal opens with, the write path Save takes, and the
# three properties that path has to hold: a no-op round trip must not touch the
# agent (writing to a Live chat agent re-provisions its map), row ORDER must
# survive (it is the order the rows reach the model), and a half-typed row must
# not fail the whole save.

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.agents.agent_config_resolver import (
	config_field_map,
	config_static_context,
	get_agent_config_for_shape,
	update_agent_config_from_shape,
)

AGENT = "ZZ WI1639 Static Context Agent"
AGENT_ID = "zz_wi1639_static_context"
MODEL = "ZZ-wi1639-model"


class TestStaticContextEditing(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.credentials = frappe.db.get_value("AI Provider", {}, "name")

	def setUp(self):
		self._cleanup()
		frappe.get_doc(
			{"doctype": "AI Model", "model_name": MODEL, "provider": self.credentials}
		).insert(ignore_permissions=True)
		self.agent = frappe.get_doc(
			{
				"doctype": "AI Agent Configuration",
				"agent_name": AGENT,
				"agent_id": AGENT_ID,
				"agent_type": "Background",
				"agent_framework": "Direct API",
				"enabled": 1,
				"ai_model": MODEL,
				"guardrails": [
					{"guardrail": "Keep generated files under 300 lines.", "category": "Code Quality", "enabled": 1},
					{"guardrail": "Never read a full table where a filter would do.", "category": "Performance", "enabled": 1},
				],
				"examples": [
					{"input": "how many staff?", "expected_output": "A single count, no preamble.", "note": "", "enabled": 1},
				],
			}
		).insert(ignore_permissions=True)

	def tearDown(self):
		self._cleanup()
		frappe.db.commit()

	def _cleanup(self):
		# Deleting only the parent row leaves the child tables behind, and the
		# agent re-inserts under the same name every setUp — so the rows pile up
		# and every count assertion drifts. Clear the children explicitly,
		# including any orphans a previous run left under the fixed name.
		parents = set(frappe.get_all("AI Agent Configuration", filters={"agent_name": AGENT}, pluck="name"))
		parents.update({AGENT_ID, AGENT})
		for table in ("AI Agent Guard Rail", "AI Agent Example"):
			frappe.db.delete(table, {"parent": ("in", list(parents))})
		frappe.db.delete("AI Agent Configuration", {"agent_name": AGENT})
		frappe.db.delete("AI Model", {"model_name": MODEL})

	# ------------------------------------------------------------------
	# read: what the modal opens with
	# ------------------------------------------------------------------
	def test_read_returns_both_tables_in_document_order(self):
		out = config_static_context(self.agent.name)

		self.assertEqual(
			[g["guardrail"] for g in out["aiGuardrails"]],
			["Keep generated files under 300 lines.", "Never read a full table where a filter would do."],
		)
		self.assertEqual(out["aiGuardrails"][0]["category"], "Code Quality")
		self.assertEqual(out["aiExamples"][0]["input"], "how many staff?")
		self.assertEqual(out["aiExamples"][0]["enabled"], 1)

	def test_shape_read_carries_the_tables_alongside_the_scalars(self):
		out = get_agent_config_for_shape(self.agent.name)

		self.assertEqual(out["aiModel"], MODEL)
		self.assertEqual(len(out["aiGuardrails"]), 2)
		self.assertEqual(len(out["aiExamples"]), 1)

	def test_dispatch_overlay_is_unaffected(self):
		"""config_field_map feeds the dispatch overlay onto shape attributes.
		These two tables are agent-owned with no shape equivalent, so leaking
		them into that map would put a list where a scalar is expected."""
		out = config_field_map(self.agent.name)

		self.assertNotIn("aiGuardrails", out)
		self.assertNotIn("aiExamples", out)

	def test_missing_config_reads_empty(self):
		"""Empty TABLES, not an empty dict — and previously neither.

		This branch used to name a `doc` that does not exist in it, so asking
		about an unknown agent raised NameError; the modal's catch turned that
		into every section silently blank. It answers now, and it answers with
		the keys present: the modal replaces each table whole, so a key it never
		receives is a table it cannot render, while one it receives empty is a
		table it can populate.
		"""
		self.assertEqual(
			config_static_context("ZZ does not exist"),
			{"aiExamples": [], "aiGuardrails": [], "aiSkills": [], "aiAgentRoles": []},
		)

	# ------------------------------------------------------------------
	# write: what Save does
	# ------------------------------------------------------------------
	def test_round_trip_with_no_edits_writes_nothing(self):
		"""The modal always sends the whole table, so an untouched Save must
		still come back clean — otherwise every open-and-close re-provisions a
		Live chat agent's map."""
		current = config_static_context(self.agent.name)

		res = update_agent_config_from_shape(self.agent.name, dict(current))

		self.assertEqual(res["updated"], [])
		self.assertFalse(res["reprovisioned"])

	def test_edit_replaces_the_table_and_keeps_the_new_order(self):
		res = update_agent_config_from_shape(
			self.agent.name,
			{
				"aiGuardrails": [
					{"guardrail": "Never read a full table where a filter would do.", "category": "Performance", "enabled": 1},
					{"guardrail": "State the token cost of a plan before running it.", "category": "Cost & Tokens", "enabled": 1},
				]
			},
		)

		self.assertIn("guardrails", res["updated"])
		after = config_static_context(self.agent.name)["aiGuardrails"]
		self.assertEqual(
			[g["guardrail"] for g in after],
			[
				"Never read a full table where a filter would do.",
				"State the token cost of a plan before running it.",
			],
		)
		# The table was replaced, not merged — the dropped rule is gone.
		self.assertNotIn("Keep generated files under 300 lines.", [g["guardrail"] for g in after])

	def test_an_omitted_table_is_left_alone(self):
		"""The selector dialog has no static-context sections, and a failed read
		leaves the modal's arrays empty. Neither may empty the agent."""
		update_agent_config_from_shape(self.agent.name, {"aiSystemPrompt": "changed"})

		after = config_static_context(self.agent.name)
		self.assertEqual(len(after["aiGuardrails"]), 2)
		self.assertEqual(len(after["aiExamples"]), 1)

	def test_an_explicitly_empty_table_clears_it(self):
		"""Removing the last row is a real edit, distinct from omitting the key."""
		update_agent_config_from_shape(self.agent.name, {"aiExamples": []})

		self.assertEqual(config_static_context(self.agent.name)["aiExamples"], [])

	def test_disabling_a_row_persists(self):
		rows = config_static_context(self.agent.name)["aiGuardrails"]
		rows[0]["enabled"] = 0

		update_agent_config_from_shape(self.agent.name, {"aiGuardrails": rows})

		after = config_static_context(self.agent.name)["aiGuardrails"]
		self.assertEqual(after[0]["enabled"], 0)
		self.assertEqual(after[1]["enabled"], 1)

	def test_a_half_typed_row_is_dropped_rather_than_failing_the_save(self):
		"""'+ Add' creates a blank row; saving before filling it in must not
		throw a mandatory-field error over the whole agent."""
		update_agent_config_from_shape(
			self.agent.name,
			{
				"aiGuardrails": [{"guardrail": "  ", "category": "Safety", "enabled": 1}],
				"aiExamples": [{"input": "", "expected_output": "typed this first", "note": "", "enabled": 1}],
			},
		)

		after = config_static_context(self.agent.name)
		self.assertEqual(after["aiGuardrails"], [])
		self.assertEqual(after["aiExamples"], [])

	def test_an_unknown_category_falls_back_rather_than_losing_the_rule(self):
		update_agent_config_from_shape(
			self.agent.name,
			{"aiGuardrails": [{"guardrail": "A rule with a bad category.", "category": "Nonsense", "enabled": 1}]},
		)

		after = config_static_context(self.agent.name)["aiGuardrails"]
		self.assertEqual(after[0]["category"], "Other")
		self.assertEqual(after[0]["guardrail"], "A rule with a bad category.")

	def test_rows_arrive_json_encoded_from_the_browser(self):
		"""frappeRequest sends `fields` as a JSON string; the tables inside it
		survive that round trip."""
		update_agent_config_from_shape(
			self.agent.name,
			frappe.as_json({"aiExamples": [{"input": "encoded", "expected_output": "ok", "note": "", "enabled": 1}]}),
		)

		after = config_static_context(self.agent.name)["aiExamples"]
		self.assertEqual(len(after), 1)
		self.assertEqual(after[0]["input"], "encoded")

	# ------------------------------------------------------------------
	# the edits have to reach the model
	# ------------------------------------------------------------------
	def test_an_edit_reaches_the_rendered_static_context(self):
		"""The agent config is cached; a Processa edit that does not invalidate
		it would look saved and change nothing at run time."""
		from one_bpmn.agents.context_assembler import load_agent_behaviour

		update_agent_config_from_shape(
			self.agent.name,
			{"aiGuardrails": [{"guardrail": "A brand new rule.", "category": "Safety", "enabled": 1}]},
		)

		behaviour = load_agent_behaviour(self.agent.name)
		self.assertIn("A brand new rule.", [g.get("guardrail") for g in behaviour.get("guardrails") or []])
