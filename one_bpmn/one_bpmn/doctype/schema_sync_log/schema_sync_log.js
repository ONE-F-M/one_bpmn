// Copyright (c) 2026, ONE BPMN and contributors
// For license information, please see license.txt

frappe.ui.form.on("Schema Sync Log", {
	refresh(frm) {
		// Status indicator colors
		const status_colors = {
			"Queued": "orange",
			"In Progress": "blue",
			"Completed": "green",
			"Failed": "red",
			"Completed with Errors": "orange",
		};

		const migration_colors = {
			"Pending": "orange",
			"Running": "blue",
			"Success": "green",
			"Failed": "red",
			"Skipped": "grey",
		};

		if (frm.doc.status) {
			frm.page.set_indicator(
				__(frm.doc.status),
				status_colors[frm.doc.status] || "grey"
			);
		}

		// Show migration status as a secondary indicator
		if (frm.doc.migration_status && frm.doc.migration_status !== "Pending") {
			frm.dashboard.set_headline(
				__("Migration: {0}", [
					`<span class="indicator-pill ${migration_colors[frm.doc.migration_status] || "grey"}">
						<span>${__(frm.doc.migration_status)}</span>
					</span>`
				])
			);
		}

		// Summary stats
		if (frm.doc.total_records_pulled > 0) {
			frm.dashboard.add_comment(
				__("Pulled {0} records — {1} applied, {2} failed", [
					frm.doc.total_records_pulled,
					frm.doc.records_applied,
					frm.doc.records_failed,
				]),
				frm.doc.records_failed > 0 ? "red" : "blue",
				true
			);
		}
	},
});
