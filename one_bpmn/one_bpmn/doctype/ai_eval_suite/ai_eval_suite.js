// Copyright (c) 2026, one-fm and contributors
// For license information, please see license.txt

frappe.ui.form.on("AI Eval Suite", {
	refresh(frm) {
		if (frm.is_new()) return;

		// Check whether this suite has at least one linked case.
		// Only show the button when cases exist.
		frappe.call({
			method: "frappe.client.get_count",
			args: {
				doctype: "AI Eval Case",
				filters: { suite: frm.doc.name },
			},
			callback(r) {
				if (!r || !r.message) return;

				frm.add_custom_button(__("Run Suite"), function () {
					frappe.freeze(__("Starting eval run…"));

					frappe.call({
						method: "one_bpmn.agents.eval_runner.run_eval_suite",
						args: { suite_name: frm.doc.name },
						callback(res) {
							frappe.unfreeze();
							if (res && res.message) {
								frappe.set_route("Form", "AI Eval Run", res.message);
							}
						},
						error() {
							frappe.unfreeze();
						},
					});
				}, __("Actions"));
			},
		});
	},
});
