# Copyright (c) 2026, one-fm and contributors
# Whitelisted endpoint that serves the connector manifests to the modeler UI.

import frappe

from one_bpmn.one_bpmn.connectors.manifest import load_manifests


@frappe.whitelist()
def get_connector_manifests():
    """Return all connector manifests for the Service Task properties panel."""
    return load_manifests()


@frappe.whitelist()
def get_connector_field_choices(source, folder=None):
    """Dynamic dropdown choices for manifest fields that declare ``choicesFrom``.

    Returns a list of ``{label, value}``. Unknown sources return [].
        driveFiles — files inside ``folder`` (id or link)
    """
    if source == "driveFiles" and folder:
        from one_bpmn.one_bpmn.integrations import google_common as gc
        from one_bpmn.one_bpmn.integrations import google_drive as gd

        try:
            files = gd.list_files(gc.normalize_drive_id(folder))
        except Exception:
            return []
        return [{"label": f.get("name") or f.get("id"), "value": f.get("id")} for f in files]

    return []
