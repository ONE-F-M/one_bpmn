// Copyright (c) 2026, one-fm and contributors
// For license information, please see license.txt

// WI-002191: the form says whether this model's credentials work, in the
// same place the person fixing them is already looking. The health_* fields
// are written by the platform; this only reads them.
frappe.ui.form.on("AI Model", {
	refresh(frm) {
		if (frm.is_new() || !frm.doc.enable_model) {
			return;
		}
		if (frm.doc.health_status === "Unhealthy") {
			frm.dashboard.set_headline(
				__("Credentials failing: {0}", [
					frappe.utils.escape_html(frm.doc.health_error_message || ""),
				]) +
					(frm.doc.health_refused_runs
						? " " + __("{0} run(s) refused so far.", [frm.doc.health_refused_runs])
						: "") +
					" " +
					__("Enter a working API key and save; runs resume once the check passes."),
				"red"
			);
		} else if (frm.doc.health_status === "Healthy" && frm.doc.health_ok_at) {
			frm.dashboard.set_headline(
				__("Credentials last verified {0}.", [
					frappe.datetime.prettyDate(frm.doc.health_ok_at),
				]),
				"green"
			);
		}
	},
});
