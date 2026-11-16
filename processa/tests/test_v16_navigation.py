import json
import os

import frappe
from frappe.tests.utils import FrappeTestCase


def _read(path: str) -> dict:
	with open(path) as f:
		return json.load(f)


class TestV16Navigation(FrappeTestCase):
	def test_every_module_ships_a_standard_sidebar(self):
		sidebars = {}
		for module in frappe.get_module_list("processa"):
			folder = os.path.join(frappe.get_app_path("processa", frappe.scrub(module)), "sidebar")
			files = [
				os.path.join(folder, name, f"{name}.json")
				for name in (os.listdir(folder) if os.path.isdir(folder) else [])
			]
			self.assertEqual(len(files), 1, module)
			sidebar = _read(files[0])
			self.assertEqual(
				(sidebar["module"], sidebar["app"], sidebar["standard"]), (module, "processa", 1)
			)
			self.assertTrue(sidebar["items"], module)
			sidebars[module] = sidebar["name"]
		self.assertEqual(len(sidebars), 13)

	def test_the_dock_opens_each_module_sidebar(self):
		dock = _read(frappe.get_app_path("processa", "dock", "processa", "processa.json"))
		self.assertEqual((dock["app"], dock["standard"]), ("processa", 1))
		names = []
		for module in frappe.get_module_list("processa"):
			folder = os.path.join(frappe.get_app_path("processa", frappe.scrub(module)), "sidebar")
			name = os.listdir(folder)[0]
			names.append(_read(os.path.join(folder, name, f"{name}.json"))["name"])
		self.assertEqual(sorted(row["link_to"] for row in dock["items"]), sorted(names))
		self.assertTrue(
			all(row["link_type"] == "Sidebar" and row["title"] and row["icon"] for row in dock["items"])
		)

	def test_the_old_workspace_sidebar_folder_is_gone(self):
		self.assertFalse(os.path.exists(frappe.get_app_path("processa", "workspace_sidebar")))
