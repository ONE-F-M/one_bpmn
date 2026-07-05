# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt

import json

import frappe
from frappe import _
from frappe.model.document import Document

# handler_type → the doctype its handler_reference points at.
HANDLER_DOCTYPES = {
	"server_script": "Server Script",
	"call_activity": "BPMN Process Model",
}


class AIAgentTool(Document):
	def _validate_links(self):
		# Frappe validates Dynamic Links BEFORE any user hook runs on insert,
		# so the target doctype must be synced from handler_type first.
		self._sync_handler_doctype()
		super()._validate_links()

	def validate(self):
		self._sync_handler_doctype()
		self._validate_input_schema()
		self._validate_required_params()
		self._validate_handler_reference()

	def _sync_handler_doctype(self):
		handler_doctype = HANDLER_DOCTYPES.get(self.handler_type)
		if not handler_doctype:
			frappe.throw(
				_("Unknown handler type '{0}'.").format(self.handler_type),
				title=_("Invalid Handler"),
			)
		self.handler_doctype = handler_doctype

	def _validate_input_schema(self):
		"""Schema shape: {"param_name": {"type": "...", "description": "..."}}."""
		try:
			schema = self.get_parsed_input_schema()
		except (TypeError, ValueError):
			frappe.throw(
				_("Input Schema must be valid JSON."), title=_("Invalid Input Schema")
			)

		if not isinstance(schema, dict):
			frappe.throw(
				_("Input Schema must be a JSON object mapping parameter names to definitions."),
				title=_("Invalid Input Schema"),
			)

		for param_name, definition in schema.items():
			if not isinstance(definition, dict) or not definition.get("type"):
				frappe.throw(
					_("Input Schema parameter '{0}' is missing a \"type\" key.").format(param_name),
					title=_("Invalid Input Schema"),
				)

	def _validate_required_params(self):
		schema_keys = set(self.get_parsed_input_schema().keys())
		for param in self.get_required_param_list():
			if param not in schema_keys:
				frappe.throw(
					_("Required parameter '{0}' is not defined in the Input Schema.").format(param),
					title=_("Invalid Required Parameters"),
				)

	def _validate_handler_reference(self):
		if not frappe.db.exists(self.handler_doctype, self.handler_reference):
			frappe.throw(
				_("{0} '{1}' does not exist.").format(self.handler_doctype, self.handler_reference),
				title=_("Invalid Handler Reference"),
			)

		if self.handler_type == "server_script":
			if frappe.db.get_value("Server Script", self.handler_reference, "disabled"):
				frappe.throw(
					_("Server Script '{0}' is disabled. Enable it before referencing it as a tool handler.").format(
						self.handler_reference
					),
					title=_("Invalid Handler Reference"),
				)

	# ── helpers used by the ToolSpec compiler (WI-001355) ─────────────

	def get_parsed_input_schema(self) -> dict:
		if isinstance(self.input_schema, dict):
			return self.input_schema
		return json.loads(self.input_schema or "{}")

	def get_required_param_list(self) -> list:
		return [p.strip() for p in (self.required_params or "").split(",") if p.strip()]
