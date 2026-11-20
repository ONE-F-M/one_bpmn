// Copyright (c) 2026, one-fm and contributors
// For license information, please see license.txt

frappe.ui.form.on("Script Approval Request", {
	refresh(frm) {
		const reaches_everything = (frm.doc.requested_items || []).some(
			(d) => d.category === "Dynamic code and reflection"
		);
		if (reaches_everything) {
			frm.set_intro(
				__("Approving Dynamic code and reflection lets this script reach items in every other category, because the check cannot see through getattr, exec or eval."),
				"red"
			);
		}
	},
});
