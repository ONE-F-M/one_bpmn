# Copyright (c) 2026, one-fm and contributors
"""Connector endpoints for the modeler: the public manifests, live field choices and the JSON export."""

import inspect

import frappe

from one_bpmn.processa_connectors import manifest


@frappe.whitelist()
def get_connector_manifests():
	"""Connector manifests for the Service Task properties panel, filtered to the connectors the caller may use.

	The filter runs here because the manifest cache is shared; dispatch enforces the same rule at runtime.
	"""
	return [m for m in manifest.load_manifests() if manifest.user_may_use_connector(m.get("connectorId"))]


@frappe.whitelist()
def get_connector_field_choices(
	connector_id: str, operation: str, field_name: str, context: str | dict | None = None
):
	"""Live {label, value} choices for a field with a Choices From path; [] when unconfigured or failing.

	The path is read from the field's configuration, never the request; context carries sibling values as kwargs.
	"""
	path = manifest.choices_source_for_field(connector_id, operation, field_name)
	if not path:
		return []

	kwargs = {}
	if context:
		parsed = frappe.parse_json(context) if isinstance(context, str) else context
		if isinstance(parsed, dict):
			kwargs = {str(k): v for k, v in parsed.items()}

	try:
		fn = frappe.get_attr(path)
		choices = _call_with_supported_kwargs(fn, kwargs)
	except Exception:
		frappe.log_error(
			title=f"Connector choices failed ({connector_id}/{operation}/{field_name})",
			message=f"path={path!r}\n\n{frappe.get_traceback()}",
		)
		return []

	out = []
	for c in choices or []:
		if isinstance(c, dict):
			out.append({"label": c.get("label") or c.get("value"), "value": c.get("value")})
		else:
			out.append({"label": str(c), "value": c})
	return out


def _call_with_supported_kwargs(fn, kwargs):
	"""Call fn with only the keyword arguments it accepts."""
	try:
		params = inspect.signature(fn).parameters
	except (TypeError, ValueError):
		return fn(**kwargs)

	if any(p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values()):
		return fn(**kwargs)
	accepted = {
		name
		for name, p in params.items()
		if p.kind in (inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY)
	}
	return fn(**{k: v for k, v in kwargs.items() if k in accepted})


@frappe.whitelist()
def export_connector(connector_id: str):
	"""One connector as a portable JSON manifest, System Manager only; secrets never travel."""
	frappe.only_for("System Manager")
	from one_bpmn.processa_connectors.seed import export_manifest

	return export_manifest(connector_id)
