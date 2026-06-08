# Copyright (c) 2026, Abdullah Almarzouq and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class AITool(Document):
	def validate(self):
		# Validate that the python_path is importable
		if self.python_path:
			try:
				parts = self.python_path.split(".")
				module_path = ".".join(parts[:-1])
				func_name = parts[-1]
				# Try importing module (do not execute anything, just check if importable)
				import importlib
				importlib.import_module(module_path)
			except ImportError:
				frappe.throw(frappe._("Python module path '{0}' is not importable.").format(module_path))
			except Exception as e:
				frappe.throw(frappe._("Invalid Python path '{0}': {1}").format(self.python_path, str(e)))
