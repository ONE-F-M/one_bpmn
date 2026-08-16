# Copyright (c) 2026, one-fm and contributors
# Manifest ⇄ DocType conversion: the bridge between the JSON manifest format and
# the BPMN Connector / Operation / Field rows that now hold connectors.
#
# It runs in three situations:
#   install/patch — seed the four shipped Google connectors into a fresh site
#   import        — bring a connector authored on another site in, as JSON
#   export        — hand a connector back out as JSON, so connectors move
#                   between sites as data instead of as patches
#
# ``import_manifest`` is idempotent: by default an existing connector is left
# alone (so a site's own edits survive a re-run), and ``overwrite=True`` replaces
# it wholesale, including deleting operations that the manifest no longer has.

import json

import frappe

from one_bpmn.one_bpmn.connectors.manifest import (
    clear_manifest_cache,
    format_choices,
    parse_choices,
)

# Manifest keys that carry execution config (never served to the browser).
_EXEC_KEY = "execution"


def import_seed_manifests(overwrite=False):
    """Import the shipped Google connectors.

    The definitions live in patches/v1_0/seed_google_connectors — there is no
    longer a manifests/ directory, because the same connector existing as both
    files and rows meant the two drifted apart the moment anyone edited a row.

    Kept as a function because the tests and the install path both want "put
    the shipped set into an empty site" without caring where it is written down.
    """
    from one_bpmn.one_bpmn.patches.v1_0.seed_google_connectors import GOOGLE_CONNECTORS

    return {
        manifest["connectorId"]: import_manifest(manifest, overwrite=overwrite)
        for manifest in GOOGLE_CONNECTORS
    }


def import_manifest(manifest, overwrite=False):
    """Create/update one connector (with its operations and fields) from a dict.

    Returns "created", "updated" or "skipped".
    """
    cid = (manifest.get("connectorId") or "").strip()
    if not cid:
        frappe.throw("Manifest has no connectorId.")

    exists = frappe.db.exists("BPMN Connector", cid)
    if exists and not overwrite:
        return "skipped"

    execution = manifest.get(_EXEC_KEY) or {}
    conn = (
        frappe.get_doc("BPMN Connector", cid)
        if exists
        else frappe.new_doc("BPMN Connector")
    )
    conn.connector_id = cid
    conn.label = manifest.get("label") or cid
    conn.description = manifest.get("description")
    conn.enabled = 1

    icon = manifest.get("icon")
    if isinstance(icon, dict):
        conn.icon_svg_path = icon.get("path")
        conn.icon_color = icon.get("color") or "#14b8a6"
        conn.icon_label = icon.get("label")
    # A string icon is a legacy name-only hint (pre-configurable icons) — the
    # renderer falls back to the default plug, so store nothing.

    api = manifest.get("api") or {}
    conn.api_name = api.get("name")
    conn.api_version = api.get("version")
    conn.discovery_url = api.get("discovery")

    # A manifest that does not say how it executes is an HTTP connector: that
    # is the default a hand-authored REST connector wants, and the shipped
    # definitions all state their type explicitly.
    conn.execution_type = execution.get("type") or "HTTP Request"
    conn.base_url = execution.get("baseUrl")
    if execution.get("timeout"):
        conn.request_timeout = int(execution["timeout"])
    conn.allow_internal_hosts = 1 if execution.get("allowInternalHosts") else 0

    auth = execution.get("auth") or {}
    conn.auth_type = auth.get("type") or "None"
    # An imported manifest carries where the secret lives, never the secret —
    # whoever imports it fills that in on the target site.
    conn.credential_source = auth.get("source") or (
        "From a settings DocType" if auth.get("settingsDoctype") else "On this connector"
    )
    conn.auth_settings_doctype = auth.get("settingsDoctype")
    conn.auth_secret_field = auth.get("secretField")
    if auth.get("headerName"):
        conn.auth_header_name = auth["headerName"]
    conn.auth_query_param = auth.get("queryParam")
    conn.auth_scopes = auth.get("scopes")

    conn.flags.ignore_permissions = True
    conn.save(ignore_permissions=True)

    keep = set()
    for idx, op in enumerate(manifest.get("operations") or [], start=1):
        name = _import_operation(cid, op, idx, overwrite=overwrite)
        if name:
            keep.add(name)

    if overwrite:
        for stale in frappe.get_all(
            "BPMN Connector Operation", filters={"connector": cid}, pluck="name"
        ):
            if stale not in keep:
                frappe.delete_doc(
                    "BPMN Connector Operation", stale, ignore_permissions=True, force=True
                )

    clear_manifest_cache()
    return "updated" if exists else "created"



def _import_operation(connector_id, op, idx, overwrite=False):
    op_id = (op.get("value") or "").strip()
    if not op_id:
        return None

    name = frappe.db.get_value(
        "BPMN Connector Operation", {"connector": connector_id, "operation_id": op_id}, "name"
    )
    if name and not overwrite:
        return name

    doc = (
        frappe.get_doc("BPMN Connector Operation", name)
        if name
        else frappe.new_doc("BPMN Connector Operation")
    )
    doc.connector = connector_id
    doc.operation_id = op_id
    doc.label = op.get("label") or op_id
    doc.api_method = op.get("method")
    doc.description = op.get("description")
    doc.enabled = 1
    doc.sort_order = idx
    doc.output_json = _dump_json(op.get("output"))

    http = op.get("http") or {}
    doc.execution_type = op.get("executionType") or ""
    doc.handler_path = op.get("handlerPath")
    if http:
        doc.http_method = http.get("method") or "POST"
        doc.url_template = http.get("url")
        doc.query_params_json = _dump_json(http.get("query"))
        doc.headers_json = _dump_json(http.get("headers"))
        doc.body_content_type = http.get("contentType") or "application/json"
        doc.body_template = (
            http["body"] if isinstance(http.get("body"), str) else _dump_json(http.get("body"))
        )
        doc.response_map_json = _dump_json(http.get("responseMap"))

    doc.set("fields", [])
    for field in op.get("fields") or []:
        doc.append("fields", _field_row(field))

    doc.flags.ignore_permissions = True
    doc.save(ignore_permissions=True)
    return doc.name


# Field types used to include DriveFile/DriveFolder — Google Drive concepts in
# the generic layer. They are now plain inputs plus a Value Transform, so a
# manifest written against the old schema is translated on import.
_LEGACY_DRIVE_TYPES = ("DriveFile", "DriveFolder")
_DRIVE_ID_TRANSFORM = "one_bpmn.one_bpmn.integrations.google_common.normalize_drive_id"


def _field_row(field):
    """A manifest field spec → a BPMN Connector Field row dict."""
    ftype = field.get("type") or "String"
    transform = field.get("transform")
    if ftype in _LEGACY_DRIVE_TYPES:
        ftype = "String"
        transform = transform or _DRIVE_ID_TRANSFORM

    row = {
        "field_name": field.get("name"),
        "field_label": field.get("label") or field.get("name"),
        "field_type": ftype,
        "required": 1 if field.get("required") else 0,
        # Manifest default is "expressions allowed" when the key is absent.
        "expression": 0 if field.get("expression") is False else 1,
        "default_value": _default_as_text(field.get("default")),
        "value_transform": transform,
        "help_text": field.get("help"),
    }
    if field.get("choicesSourcePath") or field.get("choicesFrom"):
        # choicesFrom was the pre-configuration spelling of the same idea.
        row["choices_source_path"] = field.get("choicesSourcePath") or field.get("choicesFrom")
    elif field.get("choices"):
        row["choices"] = format_choices(field["choices"])

    condition = field.get("condition") or {}
    if condition.get("field"):
        row["condition_field"] = condition["field"]
        if isinstance(condition.get("oneOf"), list):
            row["condition_operator"] = "one of"
            row["condition_value"] = ", ".join(str(v) for v in condition["oneOf"])
        else:
            row["condition_operator"] = "equals"
            row["condition_value"] = condition.get("equals")
    return row


def _default_as_text(value):
    """Field defaults are stored as text; Booleans use the panel's convention."""
    if value is None:
        return None
    if isinstance(value, bool):
        return "true" if value else ""
    return str(value)


def _dump_json(value):
    if value in (None, "", {}, []):
        return None
    return json.dumps(value, indent=2)


# ── Export ───────────────────────────────────────────────────────────────────
def export_manifest(connector_id):
    """One connector as a portable JSON manifest, execution config included.

    The inverse of ``import_manifest`` — what this returns can be imported into
    another site verbatim. Secrets are never included: only the *location* of
    the secret (settings DocType + fieldname) travels.
    """
    conn = frappe.get_doc("BPMN Connector", connector_id)

    manifest = {"connectorId": conn.connector_id, "label": conn.label}
    if conn.description:
        manifest["description"] = conn.description
    if conn.icon_svg_path:
        manifest["icon"] = {
            "path": conn.icon_svg_path,
            "color": conn.icon_color or "#14b8a6",
            "label": conn.icon_label or conn.label,
        }
    api = {
        k: v
        for k, v in (
            ("name", conn.api_name),
            ("version", conn.api_version),
            ("discovery", conn.discovery_url),
        )
        if v
    }
    if api:
        manifest["api"] = api

    execution = {"type": conn.execution_type}
    if conn.base_url:
        execution["baseUrl"] = conn.base_url
    if conn.request_timeout:
        execution["timeout"] = conn.request_timeout
    if conn.allow_internal_hosts:
        execution["allowInternalHosts"] = True
    if conn.auth_type and conn.auth_type != "None":
        # NOTE: auth_secret is deliberately absent. Only the *location* of the
        # credential travels; the secret itself never leaves the site.
        execution["auth"] = {
            k: v
            for k, v in (
                ("type", conn.auth_type),
                ("source", conn.credential_source),
                ("settingsDoctype", conn.auth_settings_doctype),
                ("secretField", conn.auth_secret_field),
                ("headerName", conn.auth_header_name),
                ("queryParam", conn.auth_query_param),
                # Scopes decide what a minted token may do. Configuration, not
                # a secret — and without them a Service Account connector
                # cannot get a token at all, so an export that dropped them
                # would import as a connector that looks right and never works.
                ("scopes", conn.auth_scopes),
            )
            if v
        }
    manifest[_EXEC_KEY] = execution

    manifest["operations"] = [
        _export_operation(name)
        for name in frappe.get_all(
            "BPMN Connector Operation",
            filters={"connector": connector_id},
            order_by="sort_order asc, operation_id asc",
            pluck="name",
        )
    ]
    return manifest


def _export_operation(name):
    op = frappe.get_doc("BPMN Connector Operation", name)
    out = {"value": op.operation_id, "label": op.label}
    if op.api_method:
        out["method"] = op.api_method
    if op.description:
        out["description"] = op.description
    if op.execution_type:
        out["executionType"] = op.execution_type
    if op.handler_path:
        out["handlerPath"] = op.handler_path

    http = {
        k: v
        for k, v in (
            ("method", op.http_method),
            ("url", op.url_template),
            ("query", _load_json(op.query_params_json)),
            ("headers", _load_json(op.headers_json)),
            ("contentType", op.body_content_type),
            ("body", op.body_template),
            ("responseMap", _load_json(op.response_map_json)),
        )
        if v
    }
    if op.url_template:
        out["http"] = http

    out["fields"] = [_export_field(f) for f in op.fields]
    output = _load_json(op.output_json)
    if output:
        out["output"] = output
    return out


def _export_field(row):
    spec = {
        "name": row.field_name,
        "label": row.field_label or row.field_name,
        "type": row.field_type,
    }
    if row.required:
        spec["required"] = True
    if not row.expression:
        spec["expression"] = False
    if row.default_value not in (None, ""):
        spec["default"] = row.default_value
    if row.value_transform:
        spec["transform"] = row.value_transform
    if row.choices_source_path:
        spec["choicesSourcePath"] = row.choices_source_path
    elif row.choices:
        spec["choices"] = parse_choices(row.choices)
    if row.condition_field and row.condition_operator:
        if row.condition_operator == "one of":
            spec["condition"] = {
                "field": row.condition_field,
                "oneOf": [v.strip() for v in (row.condition_value or "").split(",") if v.strip()],
            }
        else:
            spec["condition"] = {"field": row.condition_field, "equals": row.condition_value or ""}
    if row.help_text:
        spec["help"] = row.help_text
    return spec


def _load_json(raw):
    if not (raw or "").strip():
        return None
    try:
        return json.loads(raw)
    except ValueError:
        return None
