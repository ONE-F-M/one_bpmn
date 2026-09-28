// Copyright (c) 2026, one-fm and contributors
// For license information, please see license.txt

frappe.ui.form.on("AI Eval Case", {
	refresh(frm) {
		set_first_assertion_pass_threshold(frm);
	},
	assertions_add(frm) {
		set_first_assertion_pass_threshold(frm);
	},
	assertions_remove(frm) {
		set_first_assertion_pass_threshold(frm);
	},
});

frappe.ui.form.on("AI Eval Assertion", {
	pass_threshold(frm) {
		set_first_assertion_pass_threshold(frm);
	},
	assertions_move(frm) {
		set_first_assertion_pass_threshold(frm);
	},
});

function set_first_assertion_pass_threshold(frm) {
	const first_row = (frm.doc.assertions || [])[0];
	frm.set_value("first_assertion_pass_threshold", first_row ? first_row.pass_threshold : null);
}
