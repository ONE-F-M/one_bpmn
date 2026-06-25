// Copyright (c) 2026, one-fm and contributors
// For license information, please see license.txt

frappe.ui.form.on("AI Eval Run", {
	refresh(frm) {
		if (frm.doc.status === "Running") {
			frm.disable_save();
			frm.dashboard.set_headline(
				__("Eval run in progress — results will appear automatically.")
			);
		}
	},

	onload(frm) {
		// Subscribe to realtime completion event
		frappe.realtime.on("eval_run_completed", (data) => {
			if (data && data.run_name === frm.doc.name) {
				frm.reload_doc();
			}
		});
	},

	onload_post_render(frm) {
		// Clean up realtime listener when navigating away
		frm.page.wrapper.on("page-change", () => {
			frappe.realtime.off("eval_run_completed");
		});
	},
});
