# Copyright (c) 2026, one-fm and contributors
"""Structural validator for connector configuration: every operation resolves to an executor and every field is well formed.

Run by the test suite and by the Validate Configuration button on BPMN Connector. Checking against Google's live
discovery documents is out of scope because it needs network access.
"""

import frappe

from one_bpmn.processa_connectors.manifest import field_specs, get_execution_spec, load_manifests

# Types only describe the widget; input normalisation is a per-field Value Transform.
_VALID_TYPES = {"String", "Text", "Dropdown", "Boolean", "Hidden"}


def validate_manifests():
	"""Return a list of human-readable issue strings (empty == all good)."""
	issues = []
	# Disabled rows are included so a switched-off operation is still checked.
	manifests = load_manifests(include_disabled=True)

	seen = set()
	for m in manifests:
		cid = m.get("connectorId")
		if not cid:
			issues.append("manifest with no connectorId")
			continue
		if cid in seen:
			issues.append(f"duplicate connectorId {cid!r}")
		seen.add(cid)

		issues.extend(_validate_icon(cid, m.get("icon")))

		ops = m.get("operations")
		if not isinstance(ops, list) or not ops:
			issues.append(f"{cid}: no operations")
			continue

		for op in ops:
			ov = op.get("value")
			if not ov:
				issues.append(f"{cid}: operation missing 'value'")
				continue
			issues.extend(_validate_executability(cid, ov))
			issues.extend(_validate_fields(cid, ov, op.get("fields") or []))

	return issues


def _validate_icon(cid, icon):
	if not icon or isinstance(icon, str):
		return []  # unset, or a legacy name-only hint
	if not isinstance(icon, dict):
		return [f"{cid}: icon must be an object with path/color/label"]

	issues = []
	path = icon.get("path") or ""
	if not path:
		issues.append(f"{cid}: icon has no path")
	elif "<" in path or ">" in path:
		issues.append(f"{cid}: icon path must be SVG path data, not markup")
	return issues


def _validate_executability(cid, ov):
	"""An operation must resolve to exactly one executor.

	allow_disabled matches include_disabled above, so a connector written disabled on purpose is not reported as broken.
	"""
	try:
		spec = get_execution_spec(cid, ov, allow_disabled=True)
	except Exception as e:
		return [f"{cid}/{ov}: execution config could not be read ({e})"]

	if not spec:
		# The operation was deleted or disabled after the manifest cache was built.
		return [
			f"{cid}/{ov}: appears in the manifest but has no execution configuration "
			f"(the operation row is missing or disabled)"
		]

	if spec.handler_path:
		try:
			frappe.get_attr(spec.handler_path)
		except Exception as e:
			return [f"{cid}/{ov}: Handler Path {spec.handler_path!r} is not importable ({e})"]
		return []

	if spec.execution_type == "HTTP Request":
		issues = []
		if not spec.url_template:
			issues.append(f"{cid}/{ov}: HTTP operation has no URL Template")
		elif not spec.url_template.lower().startswith(("http://", "https://")):
			if not spec.base_url and not spec.url_template.startswith("{{"):
				issues.append(f"{cid}/{ov}: URL Template is relative but the connector has no Base URL")
		if not spec.http_method:
			issues.append(f"{cid}/{ov}: HTTP operation has no Method")
		issues += shadowed_field_access(cid, ov, spec)
		return issues

	# Python Handler with no path names nothing to call.
	return [f"{cid}/{ov}: execution type is Python Handler but no Handler Path is set"]


def shadowed_field_access(cid, ov, spec):
	"""Catch params.values: dot access in a template to a field named like a dict method, which renders the method.

	Fires only on dot access; the field name itself and bracket access are fine.
	"""
	shadowed = [n for n in field_specs(cid, ov) if hasattr({}, n)]
	if not shadowed:
		return []

	templates = " ".join(
		str(getattr(spec, attr, "") or "")
		for attr in ("url_template", "query_params_json", "headers_json", "body_template")
	)
	return [
		f"{cid}/{ov}: template uses params.{name} - that resolves to the dict method, "
		f'not the field. Use params["{name}"].'
		for name in shadowed
		if f"params.{name}" in templates
	]


def _validate_fields(cid, ov, fields):
	issues = []
	names = set()
	for f in fields:
		name = f.get("name")
		if not name:
			issues.append(f"{cid}/{ov}: field missing 'name'")
			continue
		if name in names:
			issues.append(f"{cid}/{ov}: duplicate field {name!r}")
		names.add(name)

		ftype = f.get("type", "String")
		if ftype not in _VALID_TYPES:
			issues.append(f"{cid}/{ov}/{name}: unknown field type {ftype!r}")
		if ftype == "Dropdown" and not f.get("choices") and not f.get("dynamicChoices"):
			issues.append(f"{cid}/{ov}/{name}: Dropdown field has no choices or Choices From path")

		cond = f.get("condition")
		if cond is not None:
			if not cond.get("field"):
				issues.append(f"{cid}/{ov}/{name}: condition missing 'field'")
			if "equals" not in cond and "oneOf" not in cond:
				issues.append(f"{cid}/{ov}/{name}: condition needs 'equals' or 'oneOf'")
			if isinstance(cond.get("oneOf"), list) and not cond["oneOf"]:
				issues.append(f"{cid}/{ov}/{name}: condition 'oneOf' is empty")

	# a condition can only point at a sibling field (or the operation itself)
	for f in fields:
		target = (f.get("condition") or {}).get("field")
		if target and target != "operation" and target not in names:
			issues.append(f"{cid}/{ov}/{f.get('name')}: condition refers to unknown field {target!r}")

	return issues
