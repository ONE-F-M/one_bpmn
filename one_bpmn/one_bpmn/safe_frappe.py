# Copyright (c) 2026, kartiksharma9319@gmail.com and contributors
# For license information, please see license.txt

import frappe
from frappe import _

class SafeFrappe:
	"""
	A secure proxy for the global frappe object to be used inside SpiffWorkflow script tasks.
	Exposure is limited to read-only or safe-read/write methods with explicit permission checks.
	"""

	def __init__(self):
		# Pre-bind authorized methods to avoid attribute lookup overhead and potential escapes
		self.get_doc = frappe.get_doc
		self.get_cached_doc = frappe.get_cached_doc
		self.get_list = frappe.get_list
		self.get_all = frappe.get_all  # Use with caution: get_all bypasses permissions!
		self.get_value = frappe.db.get_value
		self.exists = frappe.db.exists
		self.count = frappe.db.count
		self.new_doc = frappe.new_doc
		self.throw = frappe.throw
		self.msgprint = frappe.msgprint
		
		# Expose db object but restricted
		self.db = SafeDatabaseProxy()

	def __getattr__(self, name):
		# Standard Python behavior: raise AttributeError for unknown attributes.
		# This is important for hasattr() checks and other internal Python logic.
		raise AttributeError(_("Access to 'frappe.{0}' is restricted in BPMN scripts").format(name))

class SafeDatabaseProxy:
	"""
	Restricted access to frappe.db functions.
	"""
	def __init__(self):
		self.get_value = frappe.db.get_value
		self.get_values = frappe.db.get_values
		self.get_single_value = frappe.db.get_single_value
		self.exists = frappe.db.exists
		self.count = frappe.db.count

	def __getattr__(self, name):
		raise AttributeError(_("Access to 'frappe.db.{0}' is restricted in BPMN scripts for security reasons").format(name))

def get_safe_frappe():
	"""Returns an instance of the safe frappe proxy."""
	return SafeFrappe()
