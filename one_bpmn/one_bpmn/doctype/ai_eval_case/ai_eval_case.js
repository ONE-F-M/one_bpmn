// Copyright (c) 2026, one-fm and contributors
// For license information, please see license.txt

frappe.ui.form.on("AI Eval Case", {
	refresh(frm) {
		update_first_assertion_threshold(frm);
	},

	assertions_add(frm) {
		update_first_assertion_threshold(frm);
	},

	assertions_remove(frm) {
		update_first_assertion_threshold(frm);
	},

	assertions_move(frm) {
		update_first_assertion_threshold(frm);
	},
});

frappe.ui.form.on("AI Eval Assertion", {
	pass_threshold(frm) {
		update_first_assertion_threshold(frm);
	},

	assertion_type(frm) {
		update_first_assertion_threshold(frm);
	},
});

function update_first_assertion_threshold(frm) {
	const first_assertion = (frm.doc.assertions || [])[0];
	const show_field =
		!!first_assertion &&
		first_assertion.assertion_type === "llm_judge" &&
		!!first_assertion.pass_threshold;

	frm.set_value(
		"first_assertion_pass_threshold",
		show_field ? first_assertion.pass_threshold : null
	);
	frm.set_df_property("first_assertion_pass_threshold", "hidden", !show_field);
}
