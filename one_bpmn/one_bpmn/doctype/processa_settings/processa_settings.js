// Copyright (c) 2025, One BPMN and contributors
// For license information, please see license.txt

frappe.ui.form.on("Processa Settings", {
	refresh(frm) {
		// Intentionally left minimal. The former BA-sync "Sync Now" / "View Sync
		// Logs" buttons and headline were removed together with the daily schema
		// sync. Production comparison is now driven from the Processa canvas
		// ("Actions" → "Review Doctypes" / "Review Workflow Objects").
	},
});
