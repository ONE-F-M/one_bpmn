// Copyright (c) 2026, kartiksharma9319@gmail.com and contributors
// For license information, please see license.txt

frappe.ui.form.on("BPMN Process Instance", {
	refresh(frm) {
		// ── Pretty-print JSON fields for readability (display-only) ──
		one_bpmn.prettify_json_fields(frm, ["serialized_spec", "workflow_state"]);
	},
});
