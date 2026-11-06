import tomllib
from pathlib import Path

import frappe
from frappe.tests.utils import FrappeTestCase

PYPROJECT = Path(__file__).resolve().parents[2] / "pyproject.toml"


class TestAppMetadata(FrappeTestCase):
	def test_type_annotations_export_is_enabled(self):
		self.assertTrue(frappe.get_hooks("export_python_type_annotations"))

	def test_supported_frappe_range_is_declared(self):
		with open(PYPROJECT, "rb") as f:
			data = tomllib.load(f)
		declared = data["tool"]["bench"]["frappe-dependencies"]["frappe"]
		self.assertEqual(declared, ">=15.0.0,<16.0.0")
