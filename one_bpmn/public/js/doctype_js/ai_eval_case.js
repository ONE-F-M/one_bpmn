// Copyright (c) 2026, one-fm and contributors
// For license information, please see license.txt
//
// Surfaces the first assertion row's Pass Threshold as a read-only summary
// field near the top of the form, so a reviewer does not have to scroll into
// the Assertions table to see it.

frappe.ui.form.on("AI Eval Case", {
	refresh(frm) {
		_sync_first_assertion_pass_threshold(frm);
	},
	assertions_add(frm) {
		_sync_first_assertion_pass_threshold(frm);
	},
	assertions_remove(frm) {
		_sync_first_assertion_pass_threshold(frm);
	},
});

frappe.ui.form.on("AI Eval Assertion", {
	pass_threshold(frm) {
		_sync_first_assertion_pass_threshold(frm);
	},
});

function _sync_first_assertion_pass_threshold(frm) {
	const first_row = (frm.doc.assertions || [])[0];
	frm.set_value("first_assertion_pass_threshold", first_row ? first_row.pass_threshold : null);
}
