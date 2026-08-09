// Copyright (c) 2026, one-fm and contributors
// For license information, please see license.txt

// WI-001967: the record is immutable server-side, enforced in the controller so
// it holds for Administrator too. This only makes the form tell the truth —
// without it Administrator still sees a Save button that throws when pressed.
frappe.ui.form.on("AI Security Event", {
	refresh(frm) {
		if (frm.is_new()) return;
		frm.disable_save();
		frm.set_read_only();
		frm.dashboard.set_headline(
			__("Recorded verdict — immutable. The screened content is never stored, only its hash.")
		);
	},
});
