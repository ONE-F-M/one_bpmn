# Copyright (c) 2026, one-fm and contributors

"""No python file in the a2a and ai_agent_* modules carries a work-item id in a comment or docstring.

Only comments and module, class and function docstrings are checked. Other string literals are left
alone on purpose.
"""

import json
import os

from frappe.tests.utils import FrappeTestCase

from processa.tests.test_patch_file_ids import ROOT, comment_hits, cs, docstring_hits, read, relative

MODULES = ("a2a", "ai_agent_registry", "ai_agent_guardrails", "ai_agent_security")
APP_FILES = (
	"pyproject.toml",
	".gitignore",
	"docs/background-queues.md",
	"processa/api/a2a.py",
	"processa/api/a2a_admin.py",
)


def module_files():
	found = []
	for module in MODULES:
		for folder, _dirs, names in os.walk(os.path.join(ROOT, "processa", module)):
			found.extend(os.path.join(folder, name) for name in names if name.endswith(".py"))
	return sorted(found)


class TestModuleIds(FrappeTestCase):
	def test_the_module_folders_have_python_files(self):
		for module in MODULES:
			prefix = os.path.join(ROOT, "processa", module) + os.sep
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

	def test_no_app_level_file_carries_a_work_item_id(self):
		for name in APP_FILES:
			for number, line in enumerate(read(os.path.join(ROOT, name)).splitlines(), 1):
				self.assertIsNone(cs.WORK_ITEM_ID.search(line), f"{name}:{number} carries a work-item id")

	def test_no_processa_engine_field_description_carries_a_work_item_id(self):
		doctypes = os.path.join(ROOT, "processa", "processa_engine", "doctype")
		for folder, _dirs, names in os.walk(doctypes):
			for name in names:
				if name != os.path.basename(folder) + ".json":
					continue
				path = os.path.join(folder, name)
				for field in json.loads(read(path)).get("fields", []):
					text = field.get("description") or ""
					self.assertIsNone(cs.WORK_ITEM_ID.search(text), f"{relative(path)} field {field.get('fieldname')}")
