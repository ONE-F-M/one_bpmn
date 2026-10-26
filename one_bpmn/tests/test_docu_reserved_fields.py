"""The gate must not treat a DocType's own reserved fields as new ones.

A submittable DocType carries ``amended_from``. Docu is told to reproduce every
existing field exactly, so that field comes back in the definition — and until
the chat pipeline passed ``existing_fieldnames``, the gate rejected it and the
repair cost a full rewrite of the definition.
"""
from frappe.tests.utils import FrappeTestCase

from one_bpmn.one_bpmn.patches.v1_0.seed_docu_agent_config import _INLINE_SUB_PROMPTS
from one_bpmn.security.doctype_validator import validate_doctype_ir

_RESERVED_ON_TARGET = "amended_from"


def _ir(*fieldnames):
	return {
		"doctype_name": "Pathfinder Log",
		"module": "ONE BPMN",
		"fields": [
			{"fieldname": f, "label": f.replace("_", " ").title(), "fieldtype": "Data"}
			for f in fieldnames
		],
	}


class TestDocuReservedFields(FrappeTestCase):

	def test_reserved_field_already_on_target_passes(self):
		verdict = validate_doctype_ir(
			_ir("goal_description", _RESERVED_ON_TARGET),
			{"goal_description", _RESERVED_ON_TARGET},
		)
		self.assertTrue(verdict["valid"], verdict["violations"])

	def test_new_reserved_field_still_rejected(self):
		"""The exemption is for fields that are already there, not a blanket pass."""
		verdict = validate_doctype_ir(_ir("goal_description", _RESERVED_ON_TARGET), {"goal_description"})
		self.assertFalse(verdict["valid"])
		self.assertTrue(any(_RESERVED_ON_TARGET in v for v in verdict["violations"]))

	def test_no_existing_fields_means_a_brand_new_doctype(self):
		verdict = validate_doctype_ir(_ir("goal_description", _RESERVED_ON_TARGET))
		self.assertFalse(verdict["valid"])

	def test_both_prompts_separate_new_from_existing(self):
		"""The writer keeps existing fields; the reviewer must not then reject them."""
		for key in ("schema_writer", "schema_reviewer"):
			prompt = _INLINE_SUB_PROMPTS[key]
			self.assertIn(_RESERVED_ON_TARGET, prompt, f"{key} does not name the field that broke this")
			self.assertIn("NEW", prompt, f"{key} does not distinguish a new reserved name from an existing one")
