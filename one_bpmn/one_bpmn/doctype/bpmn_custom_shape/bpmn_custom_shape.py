# Copyright (c) 2026, ONE FM and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class BPMNCustomShape(Document):
	def validate(self):
		self.validate_svg_size()
	
	def validate_svg_size(self):
		"""Validate SVG content size (max 150KB like Lucidchart)"""
		if self.svg_content:
			size_bytes = len(self.svg_content.encode("utf-8"))
			max_size = 150 * 1024  # 150KB
			if size_bytes > max_size:
				frappe.throw(
					_("SVG content exceeds maximum size of 150KB. Current size: {0}KB").format(
						round(size_bytes / 1024, 2)
					)
				)
