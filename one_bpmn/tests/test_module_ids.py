# Copyright (c) 2026, one-fm and contributors

"""No python file in the a2a and ai_agent_* modules carries a work-item id in a comment or docstring.

Only comments and module, class and function docstrings are checked. Other string literals are left
alone on purpose.
"""

import os

from frappe.tests.utils import FrappeTestCase

from one_bpmn.tests.test_patch_file_ids import ROOT, comment_hits, docstring_hits, read, relative

MODULES = ("a2a", "ai_agent_registry", "ai_agent_guardrails", "ai_agent_security")


def module_files():
	found = []
	for module in MODULES:
		for folder, _dirs, names in os.walk(os.path.join(ROOT, "one_bpmn", module)):
			found.extend(os.path.join(folder, name) for name in names if name.endswith(".py"))
	return sorted(found)


class TestModuleIds(FrappeTestCase):
	def test_the_module_folders_have_python_files(self):
		for module in MODULES:
			prefix = os.path.join(ROOT, "one_bpmn", module) + os.sep
			self.assertTrue(
				any(path.startswith(prefix) for path in module_files()),
				f"no python files found under {prefix}",
			)

	def test_no_module_comment_carries_a_work_item_id(self):
		for path in module_files():
			for line, text in comment_hits(read(path)):
				self.fail(f"{relative(path)}:{line} has a work-item id in a comment: {text}")

	def test_no_module_docstring_carries_a_work_item_id(self):
		for path in module_files():
			for line, name in docstring_hits(read(path)):
				self.fail(f"{relative(path)}:{line} has a work-item id in the docstring of {name}")
