// Copyright (c) 2025, One BPMN and contributors
// For license information, please see license.txt

frappe.ui.form.on("Processa Settings", {
	refresh(frm) {
		// Intentionally left minimal. The former BA-sync "Sync Now" / "View Sync
		// Logs" buttons and headline were removed together with the daily schema
		// sync. Production comparison is now driven from the Processa canvas
		// ("Actions" → "Review Doctypes" / "Review Workflow Objects").

		// Add Last Synced badge to BA Sync section
		if (frm.doc.enable_ba_sync && frm.doc.ba_last_synced) {
			this.render_ba_sync_badge(frm)
		}
	},

	render_ba_sync_badge(frm) {
		// Render the Last Synced badge in the ba_last_synced field.
		// Relative time comes from frappe.datetime.comment_when - the same
		// built-in helper already used elsewhere in this app (see
		// ai_clarification_on_document.js) - rather than a hand-rolled diff.
		const field_wrapper = frm.get_field("ba_last_synced")
		if (!field_wrapper) return

		const field_element = field_wrapper.$wrapper
		if (!field_element) return

		field_element.empty()
		const badge = $(
			'<div class="d-flex align-items-center">' +
				'<div class="badge badge-blue" style="white-space: nowrap;"></div>' +
			"</div>"
		)
		badge
			.find(".badge")
			.html(frappe.datetime.comment_when(frm.doc.ba_last_synced))
		field_element.append(badge)
	},
})
