# Copyright (c) 2026, one-fm and contributors
# Connector manifests — the data-driven descriptors that declare, per provider,
# which operations exist and which fields each one exposes. Manifests are the
# single source of truth for both the modeler UI (generic properties panel) and
# runtime field handling (which inputs are expressions, which carry a Value
# Transform). Nothing here knows about any particular provider.
#
# Manifests are CONFIGURATION, held in the database:
#     BPMN Connector → BPMN Connector Operation → BPMN Connector Field
# so a whole connector — label, canvas icon, operations, fields, required flags,
# dropdown choices, conditional visibility — is authored in the desk UI with no
# code at all. The JSON files under manifests/ are the shipped SEED for a fresh
# site (imported by patches/v1_0/import_connector_manifests_to_doctype) and the
# fallback when no connector rows exist or the DB is unavailable (bench console
# without a site, early boot). Whenever a connector row exists, the DB wins.
#
# Every consumer — dispatch_connector at runtime, the properties panel via
# connectors/api.py, validator.py — reads only the dicts produced here, so where
# they are stored is invisible to them. That is the contract this module keeps:
# the emitted shape is the same schema as the on-disk JSON.

import json
import os

import frappe

_MANIFEST_DIR = os.path.join(os.path.dirname(__file__), "manifests")
_CACHE_KEY = "bpmn_connector_manifests"


# ── Public API ───────────────────────────────────────────────────────────────
def load_manifests(include_disabled=False):
    """Return every connector manifest as a list of dicts (sorted by id).

    Reads the BPMN Connector DocTypes, falling back to the seed JSON files when
    no connector rows exist (fresh install, or a bench console with no site).
    """
    if include_disabled:
        return _load_from_db(include_disabled=True) or _seed_fallback()

    cached = frappe.cache().get_value(_CACHE_KEY)
    if cached is not None:
        return cached

    manifests = _load_from_db() or _seed_fallback()
    frappe.cache().set_value(_CACHE_KEY, manifests)
    return manifests


def _seed_fallback():
    """Seed manifests as the *public* projection.

    The seed files carry an ``execution`` block for the importer; manifests are
    served to the browser, so it is stripped here. A DB-built manifest never has
    one — execution config is only ever read through get_execution_spec.
    """
    return [{k: v for k, v in m.items() if k != "execution"} for m in load_seed_manifests()]


def clear_manifest_cache():
    """Drop the cached manifests — called whenever a connector row changes."""
    frappe.cache().delete_value(_CACHE_KEY)


def get_manifest(connector_id):
    for m in load_manifests():
        if m.get("connectorId") == connector_id:
            return m
    return None


def get_operation_spec(connector_id, operation):
    """Return the operation descriptor (with its ``fields``), or None."""
    manifest = get_manifest(connector_id)
    if not manifest:
        return None
    for op in manifest.get("operations", []):
        if op.get("value") == operation:
            return op
    return None


def field_specs(connector_id, operation):
    """{fieldName: fieldSpec} for a given operation (empty dict if unknown)."""
    op = get_operation_spec(connector_id, operation)
    if not op:
        return {}
    return {f["name"]: f for f in op.get("fields", []) if f.get("name")}


def field_transforms(connector_id, operation):
    """{fieldName: dotted path} for fields declaring a Value Transform.

    Server-side only, like get_execution_spec: a transform is an internal code
    path, so it is deliberately kept out of the manifest served to the browser.
    """
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
    """The configured dotted path populating a field's dropdown, or None.

    Looked up from the database on purpose — the path must never be accepted from
    the browser, or the choices endpoint would call any function a caller names.
    """
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


def get_execution_spec(connector_id, operation):
    """Everything the dispatcher needs to *run* an operation, or None.

    Deliberately not part of the manifest: the manifest is public (it is served
    to the browser), whereas this carries the request template and the location
    of the credential. Read straight from the DocTypes, uncached.
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
        # Not migrated yet, or no site — fall back to the registry/seed path.
        return None
    if not name:
        return None

    op = frappe.get_cached_doc("BPMN Connector Operation", name)
    conn = frappe.get_cached_doc("BPMN Connector", connector_id)
    if not conn.enabled:
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
        # Where the secret lives, not the secret itself — http_ops decrypts it at
        # call time so it never sits in a cached spec.
        credential_source=conn.credential_source or "On this connector",
        auth_settings_doctype=conn.auth_settings_doctype,
        auth_secret_field=conn.auth_secret_field,
        auth_header_name=conn.auth_header_name,
        auth_query_param=conn.auth_query_param,
    )


# ── DocType → manifest projection ────────────────────────────────────────────
def _load_from_db(include_disabled=False):
    """Build manifests from the BPMN Connector DocTypes ([] if none/unavailable)."""
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
                "api_name",
                "api_version",
                "discovery_url",
            ],
            order_by="connector_id asc",
        )
    except Exception:
        # No site, no table, or the DB is not up yet — the seed files stand in.
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
    """The canvas icon, in the shape the diagram renderer wants (or None)."""
    if not row.icon_svg_path:
        return None
    return {
        "path": row.icon_svg_path.strip(),
        "color": (row.icon_color or "#14b8a6").strip(),
        "label": row.icon_label or row.label or row.connector_id,
    }


def _field_spec_from_row(row):
    """One BPMN Connector Field row → the manifest field schema."""
    spec = {
        "name": row.field_name,
        "label": row.field_label or row.field_name,
        "type": row.field_type or "String",
        "required": bool(row.required),
        "expression": bool(row.expression),
    }
    if row.default_value not in (None, ""):
        spec["default"] = row.default_value
    if row.choices_source_path:
        # The panel only needs to know the dropdown is populated live; the dotted
        # path stays server-side (it is resolved from the DB when the panel asks
        # for choices, never accepted from the browser).
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
    """``Label|value`` per line → [{label, value}]. A bare line is both."""
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
    """[{label, value}] → the ``Label|value`` text a Field row stores."""
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


# ── Seed files (fresh install / fallback) ────────────────────────────────────
def load_seed_manifests():
    """Every manifest JSON shipped in ``manifests/`` — the install seed."""
    out = []
    if not os.path.isdir(_MANIFEST_DIR):
        return out
    for fn in sorted(os.listdir(_MANIFEST_DIR)):
        if fn.endswith(".json"):
            with open(os.path.join(_MANIFEST_DIR, fn)) as f:
                out.append(json.load(f))
    return out
