# Copyright (c) 2026, one-fm and contributors
"""Docu's edit prompt shows an existing DocType without its 0 and empty properties."""

import json

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.api.docu_api import _docfield_dict
from one_bpmn.one_bpmn.patches.v1_0 import docu_edit_prompt_sends_a_compact_definition as p
from one_bpmn.tools import tool_for_server_scripts as T

# The write_schema prompt text the patch edits, as it sits in the live map.
PROMPT = (
	"Its CURRENT complete definition is below.&#10;```json&#10;"
	"{{ turn.current_ir | tojson(indent=2) }}&#10;```&#10;"
	"Keep EVERY other field exactly as above, and every Section/Column/Tab break in the same order. "
	"Do NOT say it doesn&#39;t exist."
)


class TestDocuCompactDefinition(FrappeTestCase):
	def test_compact_definition_drops_every_zero_and_empty_property(self):
		compact = T.compact_ir(T.read_doctype_definition("ToDo"))
		rows = [compact, *compact["fields"], *compact["permissions"]]
		left = [(k, v) for row in rows for k, v in row.items() if v in (0, "", None)]
		self.assertEqual(left, [])

	def test_compact_definition_applies_the_same_fields(self):
		ir = T.read_doctype_definition("ToDo")
		compact = T.compact_ir(ir)
		self.assertEqual(len(compact["fields"]), len(ir["fields"]))
		for full, short in zip(ir["fields"], compact["fields"]):
			applied = {k: v for k, v in _docfield_dict(full, 1).items() if v != 0}
			self.assertEqual(applied, _docfield_dict(short, 1))

	def test_compact_definition_keeps_what_is_set(self):
		ir = T.read_doctype_definition("ToDo")
		compact = T.compact_ir(ir)
		self.assertEqual(compact["doctype_name"], "ToDo")
		self.assertEqual(compact["sort_order"], ir["sort_order"])
		self.assertEqual([r["role"] for r in compact["permissions"]], [r["role"] for r in ir["permissions"]])
		self.assertLess(len(json.dumps(compact, indent=2)), len(json.dumps(ir, indent=2)) / 2)

	def test_a_prompt_can_call_it(self):
		ir = T.read_doctype_definition("ToDo")
		rendered = frappe.render_template("{{ compact_ir(ir) | tojson }}", {"ir": ir})
		self.assertEqual(json.loads(rendered), T.compact_ir(ir))

	def test_patch_points_the_prompt_at_the_compact_definition(self):
		edited = p.rewrite(PROMPT)
		self.assertIn("{{ compact_ir(turn.current_ir) | tojson(indent=2) }}", edited)
		self.assertNotIn("{{ turn.current_ir | tojson", edited)
		self.assertIn("leave it out of your answer too.", edited)
		self.assertEqual(p.rewrite(edited), edited)

	def test_patch_leaves_a_map_it_does_not_recognise(self):
		self.assertIsNone(p.rewrite(PROMPT.replace("every Section/Column/Tab break", "each break")))
