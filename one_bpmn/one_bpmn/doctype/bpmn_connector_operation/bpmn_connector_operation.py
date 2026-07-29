# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
#
# An operation row declares both what the modeler sees (its Fields table) and
# how the runtime executes it (a registered Python handler, or a declarative
# HTTP request). Everything checked here is checked again by
# connectors/validator.py, which sees the whole picture across connectors.

import json
import re

import frappe
from frappe import _
from frappe.model.document import Document

_OPERATION_ID_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")
_JSON_OBJECT_FIELDS = ("query_params_json", "headers_json", "response_map_json", "output_json")


class BPMNConnectorOperation(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		from one_bpmn.one_bpmn.doctype.bpmn_connector_field.bpmn_connector_field import (
			BPMNConnectorField,
		)

		api_method: DF.Data | None
		body_content_type: DF.Literal[
			"application/json", "application/x-www-form-urlencoded", "text/plain"
		]
		body_template: DF.Code | None
		connector: DF.Link
		description: DF.SmallText | None
		enabled: DF.Check
		execution_type: DF.Literal["", "HTTP Request", "Python Handler"]
		fields: DF.Table[BPMNConnectorField]
		handler_path: DF.Data | None
		headers_json: DF.Code | None
		http_method: DF.Literal["GET", "POST", "PUT", "PATCH", "DELETE"]
		label: DF.Data
		operation_id: DF.Data
		output_json: DF.Code | None
		query_params_json: DF.Code | None
		response_map_json: DF.Code | None
		sort_order: DF.Int
		url_template: DF.SmallText | None
	# end: auto-generated types

	def validate(self):
		self.validate_operation_id()
		self.validate_json_fields()
		self.validate_fields_table()
		self.validate_execution()

	@property
	def effective_execution_type(self):
		"""This operation's execution type, inheriting the connector's when blank."""
		if self.execution_type:
			return self.execution_type
		return frappe.db.get_value("BPMN Connector", self.connector, "execution_type") or "HTTP Request"

	def validate_operation_id(self):
		if not _OPERATION_ID_RE.match(self.operation_id or ""):
			frappe.throw(
				_(
					"Operation ID {0} is not valid — letters, digits and underscores "
					"only, starting with a letter (e.g. createFile). It goes into the "
					"BPMN XML verbatim."
				).format(frappe.bold(self.operation_id or ""))
			)

	def validate_json_fields(self):
		for fieldname in _JSON_OBJECT_FIELDS:
			raw = (self.get(fieldname) or "").strip()
			if not raw:
				continue
			try:
				parsed = json.loads(raw)
			except ValueError as e:
				frappe.throw(
					_("{0} is not valid JSON: {1}").format(_(self.meta.get_label(fieldname)), str(e))
				)
			if not isinstance(parsed, dict):
				frappe.throw(_("{0} must be a JSON object.").format(_(self.meta.get_label(fieldname))))

	def validate_fields_table(self):
		seen = set()
		names = {(f.field_name or "").strip() for f in self.fields}
		for row in self.fields:
			name = (row.field_name or "").strip()
			if name in seen:
				frappe.throw(_("Row {0}: duplicate field name {1}.").format(row.idx, frappe.bold(name)))
			seen.add(name)

			if (
				row.field_type == "Dropdown"
				and not (row.choices or "").strip()
				and not (row.choices_source_path or "").strip()
			):
				frappe.throw(
					_("Row {0}: a Dropdown field needs Choices or a Choices From path.").format(row.idx)
				)

			for fieldname, label in (
				("value_transform", _("Value Transform")),
				("choices_source_path", _("Choices From")),
			):
				path = (row.get(fieldname) or "").strip()
				if not path:
					continue
				try:
					target = frappe.get_attr(path)
				except Exception as e:
					frappe.throw(
						_("Row {0}: {1} {2} could not be imported: {3}").format(
							row.idx, label, frappe.bold(path), str(e)
						)
					)
				if not callable(target):
					frappe.throw(
						_("Row {0}: {1} {2} is not callable.").format(row.idx, label, frappe.bold(path))
					)

			if row.condition_field:
				if not row.condition_operator:
					frappe.throw(_("Row {0}: pick a condition Operator.").format(row.idx))
				if not (row.condition_value or "").strip():
					frappe.throw(_("Row {0}: a condition needs a Value.").format(row.idx))
				target = row.condition_field.strip()
				if target != "operation" and target not in names:
					frappe.throw(
						_(
							"Row {0}: condition refers to field {1}, which this operation "
							"does not have. Use another field's name, or the literal "
							"<code>operation</code>."
						).format(row.idx, frappe.bold(target))
					)
			elif row.condition_operator or row.condition_value:
				frappe.throw(_("Row {0}: set Only Show When Field to use a condition.").format(row.idx))

	def validate_execution(self):
		if self.effective_execution_type == "HTTP Request":
			if not (self.url_template or "").strip():
				frappe.throw(_("An HTTP operation needs a URL Template."))
			if not self.http_method:
				frappe.throw(_("An HTTP operation needs a Method."))
			self._validate_url_target()
			return

		# Python Handler
		if (self.handler_path or "").strip():
			try:
				frappe.get_attr(self.handler_path.strip())
			except Exception as e:
				frappe.throw(_("Handler Path {0} could not be imported: {1}").format(
					frappe.bold(self.handler_path), str(e)))
			return

		# No explicit path — the @connector registry must supply one. Warn rather
		# than block, so an operation can be configured before its handler ships.
		from one_bpmn.one_bpmn.connectors.registry import get_handler
		import one_bpmn.one_bpmn.connectors  # noqa: F401 — runs @connector registration

		if not get_handler(self.connector, self.operation_id):
			frappe.msgprint(
				_(
					"No registered Python handler for {0}/{1} and no Handler Path set — "
					"this operation will fail at runtime until one exists."
				).format(frappe.bold(self.connector), frappe.bold(self.operation_id)),
				indicator="orange",
				title=_("Handler missing"),
			)

	def _validate_url_target(self):
		"""A relative URL Template needs the connector to carry a Base URL."""
		url = (self.url_template or "").strip()
		if url.lower().startswith(("http://", "https://")):
			return
		if url.startswith("{{"):
			return  # fully templated — resolved at runtime
		if not frappe.db.get_value("BPMN Connector", self.connector, "base_url"):
			frappe.throw(
				_(
					"URL Template {0} is relative, so the connector needs a Base URL "
					"(or make this URL absolute)."
				).format(frappe.bold(url))
			)

	def on_update(self):
		_clear_cache()

	def on_trash(self):
		_clear_cache()


def _clear_cache():
	from one_bpmn.one_bpmn.connectors.manifest import clear_manifest_cache

	clear_manifest_cache()
