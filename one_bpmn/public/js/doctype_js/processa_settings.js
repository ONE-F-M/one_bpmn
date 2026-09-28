// Copyright (c) 2025, One BPMN and contributors
// For license information, please see license.txt

// Superseded: the Last Synced badge for the BA Sync section is implemented
// in this DocType's own controller,
// one_bpmn/one_bpmn/doctype/processa_settings/processa_settings.js, which
// Frappe loads automatically for the Processa Settings form. That version
// reuses frappe.datetime.comment_when (the same relative-time helper already
// used by ai_clarification_on_document.js) instead of the hand-rolled diff
// this file used to contain. This file is not referenced by hooks.py and is
// kept only as a placeholder to avoid a dangling doctype_js entry pointing
// at nothing; it intentionally registers no form handlers.
