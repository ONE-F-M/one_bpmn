// Copyright (c) 2025, ONE FM and contributors
// For license information, please see license.txt

frappe.ui.form.on("Process", {
	refresh(frm) {
		frm.set_value("predecessor_count", (frm.doc.depends_on || []).length);
		frm.set_value("successor_count", (frm.doc.is_required_for || []).length);
	},
	depends_on(frm) {
		frm.set_value("predecessor_count", (frm.doc.depends_on || []).length);
	},
	is_required_for(frm) {
		frm.set_value("successor_count", (frm.doc.is_required_for || []).length);
	},
});
