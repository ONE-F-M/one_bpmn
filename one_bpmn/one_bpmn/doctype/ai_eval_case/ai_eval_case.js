// Copyright (c) 2026, one-fm and contributors
// For license information, please see license.txt

frappe.ui.form.on("AI Eval Case", {
	// No form-level setup needed — child table depends_on handles visibility
});

frappe.ui.form.on("AI Eval Assertion", {
	assertion_type: function (frm, cdt, cdn) {
		frm.refresh_fields();
	},
});
