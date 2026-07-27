# Copyright (c) 2026, one-fm and contributors
# Structural validator for connector manifests. Enforces the invariant that a
# manifest faithfully mirrors the code: every manifest operation has a
# registered handler (and vice versa), and every field is well-formed with the
# enums/required flags it claims. Run as part of the test suite (see
# tests/test_connector_dispatch.py) so a manifest can't drift from its handlers.
#
# NOTE: full reconciliation against Google's live API discovery documents
# (fetching https://www.googleapis.com/discovery/v1/apis/<api>/<ver>/rest and
# diffing field names/enums) is intentionally out of scope here — it needs
# network access. This validator guarantees manifest⇄handler parity and field
# well-formedness, which is what protects the runtime.

import one_bpmn.one_bpmn.connectors  # noqa: F401 — ensures handlers are registered
from one_bpmn.one_bpmn.connectors.manifest import load_manifests
from one_bpmn.one_bpmn.connectors.registry import CONNECTORS

_VALID_TYPES = {"String", "Text", "Dropdown", "Boolean", "DriveFile", "DriveFolder", "Hidden"}


def validate_manifests():
    """Return a list of human-readable issue strings (empty == all good)."""
    issues = []
    manifests = load_manifests()

    seen = set()
    for m in manifests:
        cid = m.get("connectorId")
        if not cid:
            issues.append("manifest with no connectorId")
            continue
        if cid in seen:
            issues.append(f"duplicate connectorId {cid!r}")
        seen.add(cid)

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
            # every manifest op must have a registered handler
            if not (CONNECTORS.get(cid, {}).get(ov)):
                issues.append(f"{cid}/{ov}: manifest operation has no registered handler")
            # fields well-formed
            names = set()
            for f in op.get("fields", []) or []:
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
                if ftype == "Dropdown" and not f.get("choices") and not f.get("choicesFrom"):
                    issues.append(f"{cid}/{ov}/{name}: Dropdown field has no choices or choicesFrom")
                cond = f.get("condition")
                if cond is not None:
                    if not cond.get("field"):
                        issues.append(f"{cid}/{ov}/{name}: condition missing 'field'")
                    if "equals" not in cond and "oneOf" not in cond:
                        issues.append(f"{cid}/{ov}/{name}: condition needs 'equals' or 'oneOf'")

        # every registered handler must appear in the manifest
        for ov in CONNECTORS.get(cid, {}):
            if ov not in manifest_ops:
                issues.append(f"{cid}/{ov}: registered handler missing from manifest")

    # connectors with handlers but no manifest at all
    manifest_ids = {m.get("connectorId") for m in manifests}
    for cid in CONNECTORS:
        if cid not in manifest_ids and not cid.startswith("__"):
            issues.append(f"{cid}: handlers registered but no manifest file")

    return issues
