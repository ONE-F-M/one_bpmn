# Copyright (c) 2026, one-fm and contributors
# Whitelisted endpoints serving connector configuration to the modeler UI, plus
# the export/import pair that moves a connector between sites as JSON.
#
# get_connector_manifests is deliberately the *public* projection: it carries
# what the panel and the canvas renderer need (labels, icons, fields) and never
# the execution config (request templates, credential locations), which stays
# server-side behind manifest.get_execution_spec.

import json

import frappe

from one_bpmn.one_bpmn.connectors import manifest
from one_bpmn.one_bpmn.connectors.manifest import load_manifests


@frappe.whitelist()
def get_connector_manifests():
    """Connector manifests for the Service Task properties panel.

    Filtered to what the calling user may actually use. The filtering happens
    here rather than in ``load_manifests`` on purpose: that result is cached
    once and shared by every request, so applying a per-user rule inside it
    would serve the first caller's permissions to everyone after them.

    Hiding a connector is a convenience, not the control — dispatch enforces the
    same rule at runtime, so a diagram that already names a restricted connector
    still cannot run it.
    """
    return [
        m
        for m in load_manifests()
        if manifest.user_may_use_connector(m.get("connectorId"))
    ]


@frappe.whitelist()
def get_connector_field_choices(connector_id, operation, field_name, context=None):
    """Live dropdown choices for a field configured with a Choices From path.

    Returns a list of ``{label, value}``; anything unconfigured or failing returns
    [] so the panel degrades to an empty dropdown rather than an error.

    The function to call is read from the field's configuration, never from the
    request — accepting a dotted path from the browser would turn this endpoint
    into "call any function by name". ``context`` carries the sibling field values
    the modeler has filled in so far, passed as keyword arguments, which is how a
    dependent dropdown (files *inside* the chosen folder) works.
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
    """Call ``fn`` with only the keyword arguments it actually accepts.

    The panel sends every sibling field value; a choices function should be able
    to declare just the one or two it cares about.
    """
    import inspect

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
def export_connector(connector_id):
    """One connector as a portable JSON manifest (System Manager only).

    Includes the execution config so the result can be imported elsewhere
    verbatim; secrets never travel, only the settings DocType + fieldname that
    say where to read them.
    """
    frappe.only_for("System Manager")
    from one_bpmn.one_bpmn.connectors.seed import export_manifest

    return export_manifest(connector_id)


@frappe.whitelist()
def import_connector(manifest, overwrite=False):
    """Create/update a connector from a JSON manifest (System Manager only).

    ``overwrite`` replaces an existing connector wholesale, including deleting
    operations the manifest no longer lists; without it an existing connector is
    left untouched.
    """
    frappe.only_for("System Manager")
    from one_bpmn.one_bpmn.connectors.seed import import_manifest

    if isinstance(manifest, str):
        try:
            manifest = json.loads(manifest)
        except ValueError as e:
            frappe.throw(f"Not valid JSON: {e}")
    if not isinstance(manifest, dict):
        frappe.throw("A manifest must be a JSON object.")

    state = import_manifest(manifest, overwrite=bool(frappe.parse_json(overwrite)))
    return {"connectorId": manifest.get("connectorId"), "result": state}


@frappe.whitelist()
def validate_connectors():
    """Manifest⇄handler parity issues across every connector (diagnostics)."""
    frappe.only_for("System Manager")
    from one_bpmn.one_bpmn.connectors.validator import validate_manifests

    return validate_manifests()
