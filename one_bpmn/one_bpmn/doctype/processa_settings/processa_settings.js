// Copyright (c) 2025, One BPMN and contributors
// For license information, please see license.txt

import LastSyncedBadge from "../../../spiff/src/components/LastSyncedBadge.vue"

frappe.ui.form.on("Processa Settings", {
	refresh(frm) {
		// Intentionally left minimal. The former BA-sync "Sync Now" / "View Sync
		// Logs" buttons and headline were removed together with the daily schema
		// sync. Production comparison is now driven from the Processa canvas
		// ("Actions" → "Review Doctypes" / "Review Workflow Objects").

		// Add Last Synced badge to BA Sync section
		if (frm.doc.enable_ba_sync) {
			this.add_ba_sync_badge(frm)
		}
	},

	add_ba_sync_badge(frm) {
		const ba_sync_section = document.querySelector(
			'[data-fieldname="section_break_ba"]'
		)

		if (!ba_sync_section) return

		const existing_badge = ba_sync_section.querySelector(
			".ba-last-synced-badge-container"
		)
		if (existing_badge) {
			existing_badge.remove()
		}

		const badge_container = document.createElement("div")
		badge_container.className = "ba-last-synced-badge-container mb-2"

		const section_body = ba_sync_section.querySelector(
			".form-section-body"
		)
		if (section_body) {
			section_body.insertBefore(badge_container, section_body.firstChild)
		}

		const { createApp } = require("vue")

		const app = createApp({
			components: { LastSyncedBadge },
			template: `<LastSyncedBadge :timestamp="timestamp" />`,
			setup() {
				return {
					timestamp: frm.doc.ba_last_synced,
				}
			},
		})

		app.mount(badge_container)
	},
})
