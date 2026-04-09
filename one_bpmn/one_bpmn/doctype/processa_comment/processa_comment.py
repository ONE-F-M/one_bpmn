from frappe.model.document import Document
import frappe

class ProcessaComment(Document):
	def before_insert(self):
		if not self.author:
			self.author = frappe.session.user
		
		if not self.status:
			self.status = "Open"
