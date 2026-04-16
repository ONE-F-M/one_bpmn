// Copyright (c) 2026, kartiksharma9319@gmail.com and contributors
// For license information, please see license.txt

frappe.ui.form.on("BPMN Process Instance", {
	refresh(frm) {
		// ── Pretty-print JSON fields for readability ──
		prettify_json_field(frm, "serialized_spec");
		prettify_json_field(frm, "workflow_state");
	},
});

/**
 * Parse and pretty-print a JSON field value with 2-space indentation.
 * Silently skips empty values or invalid JSON.
 */
function prettify_json_field(frm, fieldname) {
	let raw = frm.doc[fieldname];
	if (!raw) return;

	try {
		let parsed = JSON.parse(raw);
		let formatted = JSON.stringify(parsed, null, 2);
		// Only update the control display if the value actually changed
		if (formatted !== raw) {
			frm.doc[fieldname] = formatted;
			frm.fields_dict[fieldname].refresh_input();
		}
	} catch (e) {
		// Not valid JSON — leave as-is
	}
}
