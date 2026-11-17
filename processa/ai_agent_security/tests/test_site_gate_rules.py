# Copyright (c) 2026, one-fm and contributors
"""A script writer is told what the gate refuses on this site, from Processa Settings, not a fixed list."""

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from processa.ai_agent_security.code_checks import script_validator
from processa.ai_agent_security.code_checks.script_validator import (
	ValidatorOptions,
	deep_inspect_script,
	site_gate_rules,
)

WHILE_LOOP = "i = 0\nwhile i < 3:\n    i += 1"


def _site(**switches):
	"""A site whose Processa Settings hold these gate switches."""
	return patch.object(script_validator, "_resolve_options", return_value=ValidatorOptions(**switches))


class TestSiteGateRules(FrappeTestCase):
	def test_a_site_that_accepts_while_loops_says_so_and_its_gate_agrees(self):
		with _site(block_while=False, block_all_imports=False):
			rules = site_gate_rules()
			violations = deep_inspect_script(WHILE_LOOP)

		self.assertIn("- `while` loops: accepted on this site.", rules)
		self.assertIn("- `import` lines: accepted on this site.", rules)
		self.assertEqual(violations, [])

	def test_a_site_that_refuses_while_loops_says_so_and_its_gate_agrees(self):
		with _site(block_while=True, block_all_imports=True):
			rules = site_gate_rules()
			violations = deep_inspect_script(WHILE_LOOP)

		self.assertIn("- `while` loops: refused on this site.", rules)
		self.assertIn("- `import` lines: refused on this site.", rules)
		self.assertTrue(violations)

	def test_a_prompt_template_can_print_the_rules(self):
		with _site(block_while=False):
			self.assertEqual(frappe.render_template("{{ site_gate_rules() }}", {}), site_gate_rules())
