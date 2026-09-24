// Copyright (c) 2025, One BPMN and contributors
// For license information, please see license.txt

import LastSyncedBadge from "../../spiff/src/components/LastSyncedBadge.vue";

frappe.ui.form.on("Processa Settings", {
	refresh(frm) {
		// Intentionally left minimal. The former BA-sync "Sync Now" / "View Sync
		// Logs" buttons and headline were removed together with the daily schema
		// sync. Production comparison is now driven from the Processa canvas
		// ("Actions" → "Review Doctypes" / "Review Workflow Objects").

		// Add Last Synced badge to BA Sync section if BA sync is enabled
		if (frm.doc.enable_ba_sync) {
			addLastSyncedBadge(frm);
		}
	},
});

function addLastSyncedBadge(frm) {
	// Remove existing badge container if present
	const existingContainer = document.getElementById("ba-sync-last-synced-badge");
	if (existingContainer) {
		existingContainer.remove();
	}

	// Get the BA Sync section element
	const baSyncSection = frm.get_field("enable_ba_sync");
	if (!baSyncSection || !baSyncSection.$wrapper) {
		return;
	}

	// Create a container for the badge
	const badgeContainer = document.createElement("div");
	badgeContainer.id = "ba-sync-last-synced-badge";
	badgeContainer.style.marginTop = "12px";

	// Insert the badge after the enable_ba_sync field
	const fieldWrapper = baSyncSection.$wrapper.closest(".frappe-control");
	if (fieldWrapper) {
		fieldWrapper.parentNode.insertBefore(badgeContainer, fieldWrapper.nextSibling);
	}

	// Mount the Vue component
	import("vue").then(({ createApp }) => {
		import("frappe-ui").then(() => {
			const app = createApp(LastSyncedBadge, {
				timestamp: frm.doc.ba_last_synced,
			});
			app.mount(badgeContainer);
		});
	});
}
