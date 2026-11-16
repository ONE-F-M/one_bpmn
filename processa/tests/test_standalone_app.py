# Copyright (c) 2026, ONE FM and Contributors
# See license.txt

import ast
from pathlib import Path

import frappe
from frappe.tests.utils import FrappeTestCase

OWN_APPS = {"frappe", "processa"}
OTHER_APPS = {"one_fm", "onefm_mcp", "helpdesk", "erpnext", "hrms"}


def _app_of(doctype: str) -> str | None:
	module = frappe.db.get_value("DocType", doctype, "module")
	return frappe.local.module_app.get(frappe.scrub(module)) if module else None


class TestStandaloneApp(FrappeTestCase):
	def test_doctype_links_stay_in_frappe_and_processa(self):
		modules = frappe.get_all("Module Def", filters={"app_name": "processa"}, pluck="name")
		outside = []
		for doctype in frappe.get_all("DocType", filters={"module": ["in", modules]}, pluck="name"):
			for df in frappe.get_meta(doctype).fields:
				if df.fieldtype in ("Link", "Table", "Table MultiSelect") and df.options:
					app = _app_of(df.options)
					if app not in OWN_APPS:
						outside.append(f"{doctype}.{df.fieldname} -> {df.options} ({app})")
		self.assertEqual(outside, [])

	def test_runtime_code_imports_no_other_app(self):
		root = Path(frappe.get_app_path("processa"))
		found = []
		for path in root.rglob("*.py"):
			rel = path.relative_to(root).as_posix()
			if rel.startswith("tests/") or path.name.startswith("test_"):
				continue
			for node in ast.walk(ast.parse(path.read_text())):
				if isinstance(node, ast.Import):
					names = [alias.name for alias in node.names]
				elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
					names = [node.module]
				else:
					continue
				for name in names:
					app = name.split(".")[0]
					if app in OTHER_APPS:
						found.append(f"{rel}: {name}")
		self.assertEqual(found, [])
