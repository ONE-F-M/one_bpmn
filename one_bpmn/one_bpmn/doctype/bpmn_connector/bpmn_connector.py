# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
#
# A BPMN Connector row *is* a connector manifest. Saving one changes what the
# BPMN modeler offers and what the runtime dispatcher will execute, so the
# manifest cache is cleared on every write (see connectors/manifest.py).

import re

import frappe
from frappe import _
from frappe.model.document import Document

_CONNECTOR_ID_RE = re.compile(r"^[a-z][a-z0-9_]*$")
_HEX_COLOUR_RE = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")

# Auth types whose secret is presented by the HTTP executor and therefore needs
# a place to read the secret from. "Service Account JSON" is resolved by the
# Python integrations (google_common) instead, so it needs no fields here.
_SECRET_AUTH_TYPES = ("Bearer Token", "API Key Header", "API Key Query Param", "Basic")


class BPMNConnector(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		allow_internal_hosts: DF.Check
		api_name: DF.Data | None
		api_version: DF.Data | None
		auth_header_name: DF.Data | None
		auth_query_param: DF.Data | None
		auth_secret: DF.Password | None
		auth_secret_field: DF.Data | None
		auth_settings_doctype: DF.Link | None
		auth_type: DF.Literal[
			"None",
			"Bearer Token",
			"API Key Header",
			"API Key Query Param",
			"Basic",
			"Service Account JSON",
		]
		base_url: DF.Data | None
		connector_id: DF.Data
		credential_source: DF.Literal["On this connector", "From a settings DocType"]
		description: DF.SmallText | None
		discovery_url: DF.Data | None
		enabled: DF.Check
		execution_type: DF.Literal["HTTP Request", "Python Handler"]
		icon_color: DF.Data | None
		icon_label: DF.Data | None
		icon_svg_path: DF.SmallText | None
		label: DF.Data
		request_timeout: DF.Int
	# end: auto-generated types

	def validate(self):
		self.validate_connector_id()
		self.validate_icon()
		self.validate_execution()

	def validate_connector_id(self):
		if not _CONNECTOR_ID_RE.match(self.connector_id or ""):
			frappe.throw(
				_(
					"Connector ID {0} is not valid — use lowercase letters, digits and "
					"underscores, starting with a letter (e.g. google_drive). It goes "
					"into the BPMN XML verbatim."
				).format(frappe.bold(self.connector_id or ""))
			)

	def validate_icon(self):
		# The value is injected as an SVG path's "d" attribute, so it must be
		# path data only — never markup.
		if self.icon_svg_path and re.search(r"[<>]", self.icon_svg_path):
			frappe.throw(
				_(
					"Icon SVG Path must be the path data only (the <code>d</code> "
					"attribute), not an SVG element."
				)
			)
		if self.icon_color and not _HEX_COLOUR_RE.match(self.icon_color.strip()):
			frappe.throw(_("Icon Colour must be a hex colour such as #14b8a6."))
		if self.icon_color:
			self.icon_color = self.icon_color.strip()

	def validate_execution(self):
		if self.execution_type == "HTTP Request":
			if self.request_timeout and self.request_timeout < 0:
				frappe.throw(_("Request Timeout cannot be negative."))
			if self.base_url:
				self.base_url = self.base_url.strip().rstrip("/")
				if not self.base_url.lower().startswith(("http://", "https://")):
					frappe.throw(_("Base URL must start with http:// or https://."))

		if self.auth_type in _SECRET_AUTH_TYPES:
			if self.credential_source == "From a settings DocType":
				if not (self.auth_settings_doctype and self.auth_secret_field):
					frappe.throw(
						_(
							"Credential Source is a settings DocType, so set the Secret "
							"Settings DocType and Secret Fieldname the secret is read from."
						)
					)
				field = frappe.get_meta(self.auth_settings_doctype).get_field(self.auth_secret_field)
				if not field:
					frappe.throw(
						_("{0} has no field {1}.").format(
							frappe.bold(self.auth_settings_doctype), frappe.bold(self.auth_secret_field)
						)
					)
				if field.fieldtype != "Password":
					frappe.throw(
						_(
							"{0}.{1} is a {2} field. It must be a <b>Password</b> field, so the "
							"secret is stored encrypted and readable with get_password."
						).format(
							self.auth_settings_doctype, frappe.bold(self.auth_secret_field), field.fieldtype
						)
					)
			else:
				# On-connector credential: warn rather than block, so a connector can
				# be configured before the key is to hand.
				self.credential_source = "On this connector"
				if not (self.auth_secret or self.get_password("auth_secret", raise_exception=False)):
					frappe.msgprint(
						_("Auth Type {0} is set but the Secret is empty — calls will fail until it is filled in.").format(
							frappe.bold(self.auth_type)
						),
						indicator="orange",
						title=_("Secret missing"),
					)
		if self.auth_type == "API Key Header" and not self.auth_header_name:
			frappe.throw(_("Set the API Key Header Name (e.g. X-API-Key)."))
		if self.auth_type == "API Key Query Param" and not self.auth_query_param:
			frappe.throw(_("Set the API Key Query Param (e.g. api_key)."))

	def on_update(self):
		_clear_cache()

	def on_trash(self):
		_clear_cache()

	@frappe.whitelist()
	def validate_configuration(self):
		"""Run the manifest validator and return this connector's issues.

		Surfaced as a button on the form so a modeller gets the same feedback
		the test suite gets.
		"""
		self.check_permission("read")
		from one_bpmn.one_bpmn.connectors.validator import validate_manifests

		prefix = f"{self.connector_id}"
		return [i for i in validate_manifests() if i.startswith(prefix)]


def _clear_cache():
	from one_bpmn.one_bpmn.connectors.manifest import clear_manifest_cache

	clear_manifest_cache()
