// Copyright (c) 2026, one-fm and contributors
// For license information, please see license.txt

frappe.ui.form.on("AI Eval Suite", {
	refresh(frm) {
		if (frm.is_new()) {
			return;
		}

		// Check linked case count to conditionally show the button
		frappe.xcall(
			"frappe.client.get_count",
			{ doctype: "AI Eval Case", filters: { suite: frm.doc.name } }
		).then((count) => {
			if (count > 0) {
				frm.add_custom_button(__("Run Suite"), () => {
					frm.events.run_suite(frm);
				}, __("Actions"));
			}
		});
	},

	run_suite(frm) {
		frappe.dom.freeze(__("Starting eval run…"));

		frappe.xcall(
			"one_bpmn.agents.eval_runner.run_eval_suite",
			{ suite_name: frm.doc.name }
		).then((run_name) => {
			frappe.dom.unfreeze();
			frappe.set_route("Form", "AI Eval Run", run_name);
		}).catch((err) => {
			frappe.dom.unfreeze();
			frappe.msgprint({
				title: __("Eval Run Failed"),
				indicator: "red",
				message: err.message || __("An unexpected error occurred."),
			});
		});
	},
});
