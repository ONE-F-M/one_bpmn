// Copyright (c) 2026, one-fm and contributors
// For license information, please see license.txt
//
// Surfaces the Pass Threshold of the FIRST row in Assertions as a read-only
// field near the top of the form. The server keeps this in step on save
// (see AIEvalCase._sync_first_assertion_pass_threshold), but a reviewer
// editing the table should see it update immediately, before the next save,
// rather than waiting on a round trip.

function sync_first_assertion_pass_threshold(frm) {
	const first = frm.doc.assertions && frm.doc.assertions[0];
	frm.set_value("first_assertion_pass_threshold", first ? first.pass_threshold : null);
}

frappe.ui.form.on("AI Eval Case", {
	refresh: sync_first_assertion_pass_threshold,
});

frappe.ui.form.on("AI Eval Assertion", {
	assertions_add: sync_first_assertion_pass_threshold,
	assertions_remove: sync_first_assertion_pass_threshold,
	pass_threshold: sync_first_assertion_pass_threshold,
});
