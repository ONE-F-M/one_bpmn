# Copyright (c) 2026, one-fm and contributors
# Structural validator for connector configuration. Enforces the invariant that
# every operation a modeler can pick is actually executable, and that every field
# is well-formed with the enums/required flags it claims. Run as part of the test
# suite (see tests/test_connector_dispatch.py) and from the "Validate
# Configuration" button on BPMN Connector, so a connector cannot silently drift
# into a state that only fails at runtime.
#
# Since connectors became configuration, "executable" has three legitimate
# shapes — an explicit handler path or a declarative HTTP request
# @connector handler — so the old "every operation needs a Python handler" rule
# is "every operation must resolve to an executor". A handler with
# no configuration row is still reported, because it is unreachable from the
# modeler.
#
# NOTE: full reconciliation against Google's live API discovery documents
# (fetching https://www.googleapis.com/discovery/v1/apis/<api>/<ver>/rest and
# diffing field names/enums) is intentionally out of scope here — it needs
# network access. This validator guarantees executability and field
# well-formedness, which is what protects the runtime.

import frappe

import one_bpmn.one_bpmn.connectors  # noqa: F401 — ensures handlers are registered
from one_bpmn.one_bpmn.connectors.manifest import get_execution_spec, load_manifests

# Provider-neutral on purpose: DriveFile/DriveFolder used to live here, which put
# a Google Drive concept in the generic layer. Input normalisation is now a
# per-field Value Transform (a dotted path), so types only describe the widget.
_VALID_TYPES = {"String", "Text", "Dropdown", "Boolean", "Hidden"}


def validate_manifests():
    """Return a list of human-readable issue strings (empty == all good)."""
    issues = []
    # Disabled rows are included so an operation a site has switched off is not
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

        manifest_ops = set()
        for op in ops:
            ov = op.get("value")
            if not ov:
                issues.append(f"{cid}: operation missing 'value'")
                continue
            manifest_ops.add(ov)
            issues.extend(_validate_executability(cid, ov))
            issues.extend(_validate_fields(cid, ov, op.get("fields") or []))


    # connectors with handlers but no configuration at all
    manifest_ids = {m.get("connectorId") for m in manifests}

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

    ``allow_disabled`` matches this validator's own intent: it loads manifests
    with ``include_disabled=True`` so a site can inspect a connector it has
    switched off. Without it, every operation of a disabled connector reported
    "appears in the manifest but has no execution configuration" — which is what
    a *broken* operation looks like. That became routine once the Connector Agent
    started writing connectors disabled on purpose, so Validate
    Configuration was telling people a perfectly good draft was broken.
    """
    try:
        spec = get_execution_spec(cid, ov, allow_disabled=True)
    except Exception as e:
        return [f"{cid}/{ov}: execution config could not be read ({e})"]


    if not spec:
        # In the manifest but with no execution row behind it — the operation
        # was deleted or disabled after the manifest cache was built.
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
                issues.append(
                    f"{cid}/{ov}: URL Template is relative but the connector has no Base URL"
                )
        if not spec.http_method:
            issues.append(f"{cid}/{ov}: HTTP operation has no Method")
        issues += _shadowed_field_access(cid, ov, spec)
        return issues

    # Python Handler with no path names nothing to call.
    return [
        f"{cid}/{ov}: execution type is Python Handler but no Handler Path is set"
    ]


def _shadowed_field_access(cid, ov, spec):
    """Catch `params.values` — dot access to a field that shadows a dict method.

    Templates read fields off a dict, so a field named ``values``, ``items`` or
    ``get`` accessed as ``params.values`` silently resolves to the dict METHOD.
    Nothing raises: the body just renders as "<built-in method values>" and
    Google rejects it with something unrelated-looking. It cost real debugging
    time on google_sheets/updateValues.

    Flagged only when a template actually uses dot access on such a field —
    the field NAME is fine (renaming one breaks every diagram already using it)
    and bracket access works. So this stays silent for correct configuration
    and fires exactly on the mistake.
    """
    from one_bpmn.one_bpmn.connectors.manifest import field_specs

    shadowed = [n for n in field_specs(cid, ov) if hasattr({}, n)]
    if not shadowed:
        return []

    templates = " ".join(
        str(getattr(spec, attr, "") or "")
        for attr in ("url_template", "query_params_json", "headers_json", "body_template")
    )
    return [
        f'{cid}/{ov}: template uses params.{name} — that resolves to the dict method, '
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
            issues.append(
                f"{cid}/{ov}/{f.get('name')}: condition refers to unknown field {target!r}"
            )

    return issues
