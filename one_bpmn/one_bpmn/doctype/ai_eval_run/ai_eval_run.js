// Copyright (c) 2026, one-fm and contributors
// For license information, please see license.txt

frappe.ui.form.on("AI Eval Run", {
	refresh(frm) {
		if (frm.doc.status !== "Running") return;

		// Subscribe to the realtime event published by the eval runner
		// background job. When the run finishes, reload the form to show
		// the final status and results child table.
		frappe.realtime.on("eval_run_completed", function (data) {
			if (data && data.run_name === frm.doc.name) {
				frappe.show_alert({
					message: __("Eval run completed — status: {0}", [data.status]),
					indicator: data.status === "Passed" ? "green" : "red",
				});
				frm.reload_doc();
			}
		});
	},

	onload(frm) {
		// Clean up the listener when navigating away to prevent stacking
		// multiple listeners across page loads.
		frm.page.wrapper.on("page-change", function () {
			frappe.realtime.off("eval_run_completed");
		});
	},
});
