# Copyright (c) 2026, one-fm and contributors
"""No Python file under ai_agent_registry/definitions is over 800 lines."""

import os

from frappe.tests.utils import FrappeTestCase

DEFINITIONS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "definitions")
MAX_LINES = 800


class TestDefinitionsFileSize(FrappeTestCase):
	def test_every_definitions_file_is_at_most_800_lines(self):
		checked = 0
		for folder, _dirs, names in os.walk(DEFINITIONS):
			for name in names:
				if not name.endswith(".py"):
					continue
				path = os.path.join(folder, name)
				with open(path, encoding="utf-8") as handle:
					lines = sum(1 for _ in handle)
				checked += 1
				self.assertLessEqual(lines, MAX_LINES, os.path.relpath(path, DEFINITIONS))
		self.assertTrue(checked)
