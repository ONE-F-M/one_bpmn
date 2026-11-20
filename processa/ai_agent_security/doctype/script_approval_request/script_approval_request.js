// Copyright (c) 2026, one-fm and contributors
// For license information, please see license.txt

frappe.ui.form.on("Script Approval Request", {
	refresh(frm) {
		const is_open = ["Pending Review", "Pending Approval"].includes(frm.doc.status);
		if (!frm.is_new() && is_open && !frm.doc.__onload?.approval_started) {
			frm.dashboard.set_headline_alert(
				__("The approval process did not start for this request."),
				"orange"
			);
			frm.add_custom_button(__("Retry"), async () => {
				const { message } = await frappe.call({
					method: "processa.api.script_approvals.retry_script_approval",
					args: { request: frm.doc.name },
				});
				if (!message.started) {
					frappe.throw(__("The approval process still did not start. Check that the Script Security Approval map is deployed."));
				}
				frm.reload_doc();
			});
		}
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
