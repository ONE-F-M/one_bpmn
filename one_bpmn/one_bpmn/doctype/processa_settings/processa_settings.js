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
		// Render the Last Synced badge in the ba_last_synced field
		const field_wrapper = frm.get_field("ba_last_synced")
		if (!field_wrapper) return

		// Access the actual field element
		const field_element = field_wrapper.$wrapper
		if (!field_element) return

		// Clear previous content
		field_element.innerHTML = ""

		// Create a simple badge display using HTML
		// We'll render the relative time directly using the same logic
		// as the LastSyncedBadge component
		const relative_time = this.get_relative_time(frm.doc.ba_last_synced)
		const badge_html = `
			<div class="d-flex align-items-center">
				<div class="badge badge-blue" style="white-space: nowrap;">
					${frappe.escape_html(relative_time)}
				</div>
			</div>
		`
		field_element.innerHTML = badge_html
	},

	get_relative_time(timestamp) {
		if (!timestamp) {
			return "Invalid date"
		}

		const now = new Date()
		const syncDate = new Date(timestamp)

		if (isNaN(syncDate.getTime())) {
			return "Invalid date"
		}

		const diffMs = now.getTime() - syncDate.getTime()
		const diffSec = Math.floor(diffMs / 1000)
		const diffMin = Math.floor(diffSec / 60)
		const diffHours = Math.floor(diffMin / 60)
		const diffDays = Math.floor(diffHours / 24)
		const diffWeeks = Math.floor(diffDays / 7)

		if (diffSec < 60) {
			return "just now"
		} else if (diffMin < 60) {
			const mins = Math.max(1, diffMin)
			return `${mins} minute${mins > 1 ? "s" : ""} ago`
		} else if (diffHours < 24) {
			return `${diffHours} hour${diffHours > 1 ? "s" : ""} ago`
		} else if (diffDays < 7) {
			return `${diffDays} day${diffDays > 1 ? "s" : ""} ago`
		} else if (diffWeeks < 4) {
			return `${diffWeeks} week${diffWeeks > 1 ? "s" : ""} ago`
		} else {
			const months = Math.floor(diffDays / 30)
			if (months < 12) {
				return `${months} month${months > 1 ? "s" : ""} ago`
			}
			const years = Math.floor(months / 12)
			return `${years} year${years > 1 ? "s" : ""} ago`
		}
	},
})
