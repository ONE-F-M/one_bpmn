// Copyright (c) 2026, kartiksharma9319@gmail.com and contributors
// For license information, please see license.txt

frappe.ui.form.on("BPMN Process Model", {
	refresh(frm) {
		// Add "Open in Editor" button
		if (!frm.is_new()) {
			frm.add_custom_button(__("Open in Editor"), function () {
				frappe.set_route("spiff", "process", frm.doc.process, "diagram", frm.doc.name);
			});
		}
	},
});
