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
		// Dynamically import Vue and the component
		import("vue").then(({ createApp }) => {
			import("../../../spiff/src/components/LastSyncedBadge.vue").then(
				(module) => {
					const LastSyncedBadge = module.default

					// Find the section that contains ba_last_synced field
					const field_wrapper = frm.get_field("ba_last_synced")
					if (!field_wrapper) return

					const container = field_wrapper.$wrapper
					if (!container) return

					// Clear any existing Vue app
					const existing_app = container.__vue_app
					if (existing_app) {
						existing_app.unmount()
					}

					// Create and mount the Vue app
					const app = createApp({
						components: { LastSyncedBadge },
						template: `
							<div class="d-flex align-items-center gap-2">
								<span class="text-muted text-sm">Last Synced:</span>
								<LastSyncedBadge :timestamp="timestamp" />
							</div>
						`,
						setup() {
							return {
								timestamp: frm.doc.ba_last_synced,
							}
						},
					})

					// Store reference for cleanup
					container.__vue_app = app
					app.mount(container)
				}
			)
		})
	},
})
