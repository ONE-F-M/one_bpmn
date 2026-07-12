// Copyright (c) 2026, one-fm and contributors
// For license information, please see license.txt

frappe.ui.form.on("AI Agent Tool", {
	handler_type(frm) {
		// handler_reference targets a different doctype per handler type;
		// clear a stale reference so the Dynamic Link can't point at the
		// wrong doctype. The server-side controller keeps handler_doctype
		// authoritative on validate.
		frm.set_value(
			"handler_doctype",
			frm.doc.handler_type === "call_activity" ? "BPMN Process Model" : "Server Script"
		);
		frm.set_value("handler_reference", "");
	},

	refresh(frm) {
		frm.set_query("handler_reference", () => {
			if (frm.doc.handler_type === "server_script") {
				return { filters: { disabled: 0 } };
			}
			return {};
		});
	},
});
