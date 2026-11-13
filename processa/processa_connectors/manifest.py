# Copyright (c) 2026, one-fm and contributors
"""Connector manifests projected from BPMN Connector, Operation and Field rows.

The modeler panel, dispatch and the validator read only the dicts built here. The manifest is public and cached for
everyone; execution config and per-user role rules stay outside it.
"""

import json

import frappe

_CACHE_KEY = "bpmn_connector_manifests"
_ROLES_CACHE_KEY = "bpmn_connector_allowed_roles"
_OPERATIONS_CACHE_KEY = "bpmn_connector_operations_by_key"


def load_manifests(include_disabled=False):
	"""Every connector manifest as a list of dicts sorted by id; [] when there are no rows or no database."""
	if include_disabled:
		return _load_from_db(include_disabled=True)

	cached = frappe.cache().get_value(_CACHE_KEY)
	if cached is not None:
		return cached

	manifests = _load_from_db()
	frappe.cache().set_value(_CACHE_KEY, manifests)
	return manifests


def clear_manifest_cache():
	"""Drop the cached manifests; called whenever a connector row changes."""
	frappe.cache().delete_value(_CACHE_KEY)
	frappe.cache().delete_value(_ROLES_CACHE_KEY)
	frappe.cache().delete_value(_OPERATIONS_CACHE_KEY)


def allowed_roles_by_connector():
	"""{connector_id: {role, ...}} for the connectors that restrict themselves.

	Kept out of the manifest, whose cache is shared by every user.
	"""
	cached = frappe.cache().get_value(_ROLES_CACHE_KEY)
	if cached is not None:
		return {k: set(v) for k, v in cached.items()}

	mapping = {}
	try:
		if frappe.db and frappe.db.table_exists("BPMN Connector Role"):
			rows = frappe.get_all(
				"BPMN Connector Role",
				filters={"parenttype": "BPMN Connector"},
				fields=["parent", "role"],
			)
			by_parent = {}
			for row in rows:
				if row.role:
					by_parent.setdefault(row.parent, set()).add(row.role)
			# parent is the DocType name; callers know a connector by connector_id.
			ids = {
				c.name: c.connector_id
				for c in frappe.get_all(
					"BPMN Connector",
					filters={"name": ["in", list(by_parent)]} if by_parent else {"name": ""},
					fields=["name", "connector_id"],
				)
			}
			mapping = {ids[p]: r for p, r in by_parent.items() if p in ids}
	except Exception:
		# An unreadable table means no known restrictions; the runtime check still applies.
		return {}

	frappe.cache().set_value(_ROLES_CACHE_KEY, {k: sorted(v) for k, v in mapping.items()})
	return mapping


def user_may_use_connector(connector_id, user=None):
	"""Whether user may use this connector: open when it has no Allowed Roles, and always to Administrator."""
	required = allowed_roles_by_connector().get(connector_id)
	if not required:
		return True
	user = user or frappe.session.user
	if user == "Administrator":
		return True
	return bool(required & set(frappe.get_roles(user)))


def get_operation_spec(connector_id, operation):
	"""Return the operation descriptor (with its ``fields``), or None."""
	return _operations_by_key().get((connector_id, operation))


def _operations_by_key():
	"""{(connector_id, operation): operation descriptor} over the enabled manifests, cached with them."""
	cached = frappe.cache().get_value(_OPERATIONS_CACHE_KEY)
	if cached is None:
		cached = {
			(m["connectorId"], op.get("value")): op
			for m in load_manifests()
			for op in m.get("operations", [])
		}
		frappe.cache().set_value(_OPERATIONS_CACHE_KEY, cached)
	return cached


def field_specs(connector_id, operation):
	"""{fieldName: fieldSpec} for a given operation (empty dict if unknown)."""
	op = get_operation_spec(connector_id, operation)
	if not op:
		return {}
	return {f["name"]: f for f in op.get("fields", []) if f.get("name")}


def field_transforms(connector_id, operation):
	"""{fieldName: dotted path} for fields declaring a Value Transform; server-side only, like get_execution_spec."""
	try:
		if not frappe.db or not frappe.db.table_exists("BPMN Connector Field"):
			return {}
		parent = frappe.db.get_value(
			"BPMN Connector Operation",
			{"connector": connector_id, "operation_id": operation},
			"name",
		)
		if not parent:
			return {}
		rows = frappe.get_all(
			"BPMN Connector Field",
			filters={
				"parent": parent,
				"parenttype": "BPMN Connector Operation",
				"value_transform": ("is", "set"),
			},
			fields=["field_name", "value_transform"],
		)
	except Exception:
		return {}
	return {r.field_name: r.value_transform.strip() for r in rows if r.value_transform}


def choices_source_for_field(connector_id, operation, field_name):
	"""The configured dotted path populating a field's dropdown, or None; read from the database, never from the browser."""
	parent = frappe.db.get_value(
		"BPMN Connector Operation",
		{"connector": connector_id, "operation_id": operation, "enabled": 1},
		"name",
	)
	if not parent:
		return None
	return frappe.db.get_value(
		"BPMN Connector Field",
		{"parent": parent, "parenttype": "BPMN Connector Operation", "field_name": field_name},
		"choices_source_path",
	)


def get_execution_spec(connector_id, operation, allow_disabled=False):
	"""Everything the dispatcher needs to run an operation, or None, read uncached from the DocTypes.

	Kept out of the public manifest. allow_disabled lets the Connector Agent test a connector it wrote disabled.
	"""
	try:
		if not frappe.db or not frappe.db.table_exists("BPMN Connector Operation"):
			return None
		name = frappe.db.get_value(
			"BPMN Connector Operation",
			{"connector": connector_id, "operation_id": operation, "enabled": 1},
			"name",
		)
	except Exception:
		# Not migrated yet, or no site.
		return None
	if not name:
		return None

	op = frappe.get_cached_doc("BPMN Connector Operation", name)
	conn = frappe.get_cached_doc("BPMN Connector", connector_id)
	if not conn.enabled and not allow_disabled:
		return None

	return frappe._dict(
		connector_id=connector_id,
		operation=operation,
		execution_type=op.execution_type or conn.execution_type or "HTTP Request",
		handler_path=(op.handler_path or "").strip(),
		http_method=op.http_method or "POST",
		url_template=(op.url_template or "").strip(),
		query_params_json=op.query_params_json,
		headers_json=op.headers_json,
		body_content_type=op.body_content_type or "application/json",
		body_template=op.body_template,
		response_map_json=op.response_map_json,
		base_url=(conn.base_url or "").strip().rstrip("/"),
		request_timeout=conn.request_timeout or 30,
		allow_internal_hosts=bool(conn.allow_internal_hosts),
		auth_type=conn.auth_type or "None",
		# Where the secret lives; operations/http.py decrypts it at call time.
		credential_source=conn.credential_source or "On this connector",
		auth_settings_doctype=conn.auth_settings_doctype,
		auth_secret_field=conn.auth_secret_field,
		auth_header_name=conn.auth_header_name,
		auth_query_param=conn.auth_query_param,
		auth_scopes=conn.auth_scopes,
	)


def _load_from_db(include_disabled=False):
	"""Build manifests from the BPMN Connector DocTypes; [] if none or unavailable."""
	try:
		if not frappe.db or not frappe.db.table_exists("BPMN Connector"):
			return []
		filters = {} if include_disabled else {"enabled": 1}
		connectors = frappe.get_all(
			"BPMN Connector",
			filters=filters,
			fields=[
				"name",
				"connector_id",
				"label",
				"description",
				"icon_svg_path",
				"icon_color",
				"icon_label",
				"icon_stroke",
				"api_name",
				"api_version",
				"discovery_url",
			],
			order_by="connector_id asc",
		)
	except Exception:
		# No site, no table, or the database is not up yet.
		return []

	if not connectors:
		return []

	operations = _operations_by_connector(include_disabled=include_disabled)
	return [_manifest_from_row(c, operations.get(c.connector_id, [])) for c in connectors]


def _operations_by_connector(include_disabled=False):
	"""{connector_id: [operation dict, ...]} in modeler display order."""
	filters = {} if include_disabled else {"enabled": 1}
	rows = frappe.get_all(
		"BPMN Connector Operation",
		filters=filters,
		fields=[
			"name",
			"connector",
			"operation_id",
			"label",
			"api_method",
			"description",
			"output_json",
		],
		order_by="connector asc, sort_order asc, operation_id asc",
	)
	if not rows:
		return {}

	fields_by_parent = _fields_by_parent([r.name for r in rows])

	out = {}
	for r in rows:
		op = {"value": r.operation_id, "label": r.label or r.operation_id}
		if r.api_method:
			op["method"] = r.api_method
		if r.description:
			op["description"] = r.description
		op["fields"] = fields_by_parent.get(r.name, [])
		output = _parse_json_object(r.output_json)
		if output:
			op["output"] = output
		out.setdefault(r.connector, []).append(op)
	return out


def _fields_by_parent(parents):
	"""{operation name: [field spec, ...]} in row order."""
	rows = frappe.get_all(
		"BPMN Connector Field",
		filters={"parent": ("in", parents), "parenttype": "BPMN Connector Operation"},
		fields=[
			"parent",
			"idx",
			"field_name",
			"field_label",
			"field_type",
			"required",
			"expression",
			"default_value",
			"value_transform",
			"choices",
			"choices_source_path",
			"condition_field",
			"condition_operator",
			"condition_value",
			"help_text",
		],
		order_by="parent asc, idx asc",
	)
	out = {}
	for r in rows:
		out.setdefault(r.parent, []).append(_field_spec_from_row(r))
	return out


def _manifest_from_row(row, operations):
	manifest = {"connectorId": row.connector_id, "label": row.label or row.connector_id}
	if row.description:
		manifest["description"] = row.description
	icon = _icon_from_row(row)
	if icon:
		manifest["icon"] = icon
	api = {}
	if row.api_name:
		api["name"] = row.api_name
	if row.api_version:
		api["version"] = row.api_version
	if row.discovery_url:
		api["discovery"] = row.discovery_url
	if api:
		manifest["api"] = api
	manifest["operations"] = operations
	return manifest


def _icon_from_row(row):
	"""The canvas icon in the shape the diagram renderer wants, or None."""
	if not row.icon_svg_path:
		return None
	return {
		"path": row.icon_svg_path.strip(),
		"color": (row.icon_color or "#14b8a6").strip(),
		"label": row.icon_label or row.label or row.connector_id,
		# Outline icons are drawn as lines; filling one leaves unreadable slivers.
		"stroke": bool(row.icon_stroke),
	}


def _field_spec_from_row(row):
	"""One BPMN Connector Field row as the manifest field schema."""
	spec = {
		"name": row.field_name,
		"label": row.field_label or row.field_name,
		"type": row.field_type or "String",
		"required": bool(row.required),
		"expression": bool(row.expression),
	}
	if row.default_value not in (None, ""):
		# A Boolean default is stored as text, and "false" is truthy in the browser.
		spec["default"] = (
			str(row.default_value).strip().lower() in ("1", "true", "yes", "on")
			if (row.field_type or "String") == "Boolean"
			else row.default_value
		)
	if row.choices_source_path:
		# The dotted path stays server-side; the panel only learns the choices are live.
		spec["dynamicChoices"] = True
	elif row.choices:
		choices = parse_choices(row.choices)
		if choices:
			spec["choices"] = choices
	condition = _condition_from_row(row)
	if condition:
		spec["condition"] = condition
	if row.help_text:
		spec["help"] = row.help_text
	return spec


def _condition_from_row(row):
	if not row.condition_field or not row.condition_operator:
		return None
	value = row.condition_value or ""
	field = row.condition_field.strip()
	if row.condition_operator == "one of":
		return {"field": field, "oneOf": [v.strip() for v in value.split(",") if v.strip()]}
	return {"field": field, "equals": value}


def parse_choices(raw):
	"""``Label|value`` per line as [{label, value}]. A bare line is both."""
	out = []
	for line in (raw or "").splitlines():
		line = line.strip()
		if not line:
			continue
		if "|" in line:
			label, _, value = line.partition("|")
			out.append({"label": label.strip(), "value": value.strip()})
		else:
			out.append({"label": line, "value": line})
	return out


def format_choices(choices):
	"""[{label, value}] as the ``Label|value`` text a Field row stores."""
	lines = []
	for c in choices or []:
		if isinstance(c, str):
			lines.append(c)
		else:
			label, value = c.get("label", ""), c.get("value", "")
			lines.append(value if label == value else f"{label}|{value}")
	return "\n".join(lines)


def _parse_json_object(raw):
	if not (raw or "").strip():
		return None
	try:
		parsed = json.loads(raw)
	except ValueError:
		return None
	return parsed if isinstance(parsed, dict) else None
