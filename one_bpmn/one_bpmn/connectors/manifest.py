# Copyright (c) 2026, one-fm and contributors
# Connector manifests — the data-driven descriptors that declare, per provider,
# which operations exist and which fields each one exposes. Manifests are the
# single source of truth for both the modeler UI (generic properties panel) and
# runtime field handling (which inputs are expressions, which are Drive
# file/folder ids to normalize).
#
# Each manifest is a faithful projection of the target provider's real API:
# operations = API methods, field enums/required-ness = the API's own.

import json
import os

_MANIFEST_DIR = os.path.join(os.path.dirname(__file__), "manifests")


def load_manifests():
    """Return every connector manifest as a list of dicts (sorted by file)."""
    out = []
    if not os.path.isdir(_MANIFEST_DIR):
        return out
    for fn in sorted(os.listdir(_MANIFEST_DIR)):
        if fn.endswith(".json"):
            with open(os.path.join(_MANIFEST_DIR, fn)) as f:
                out.append(json.load(f))
    return out


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
