// Copyright (c) 2025, One BPMN and contributors
// For license information, please see license.txt

frappe.ui.form.on("Processa Settings", {
	refresh(frm) {
		// Intentionally left minimal. The former BA-sync "Sync Now" / "View Sync
		// Logs" buttons and headline were removed together with the daily schema
		// sync. Production comparison is now driven from the Processa canvas
		// ("Actions" → "Review Doctypes" / "Review Workflow Objects").

		// Add Last Synced badge to BA Sync section if BA sync is enabled
		if (frm.doc.enable_ba_sync && frm.doc.ba_last_synced) {
			addLastSyncedBadge(frm);
		}
	},

	enable_ba_sync(frm) {
		// Update badge when enable_ba_sync is toggled
		if (frm.doc.enable_ba_sync) {
			addLastSyncedBadge(frm);
		} else {
			removeLastSyncedBadge();
		}
	},
});

function addLastSyncedBadge(frm) {
	// Remove existing badge container if present
	removeLastSyncedBadge();

	if (!frm.doc.ba_last_synced) {
		return;
	}

	// Get the BA Sync section element
	const baSyncSection = frm.get_field("enable_ba_sync");
	if (!baSyncSection || !baSyncSection.$wrapper) {
		return;
	}

	// Create a container for the badge with relative time string
	const badgeContainer = document.createElement("div");
	badgeContainer.id = "ba-sync-last-synced-badge";
	badgeContainer.style.marginTop = "12px";
	badgeContainer.innerHTML = `
		<span class="badge" style="background-color: var(--blue-500, #3b82f6); color: white; padding: 4px 8px; border-radius: 4px; font-size: 12px; white-space: nowrap;">
			Last synced: ${formatRelativeTime(frm.doc.ba_last_synced)}
		</span>
	`;

	// Insert the badge after the enable_ba_sync field
	const fieldWrapper = baSyncSection.$wrapper.closest(".frappe-control");
	if (fieldWrapper) {
		fieldWrapper.parentNode.insertBefore(badgeContainer, fieldWrapper.nextSibling);
	}
}

function removeLastSyncedBadge() {
	const existingContainer = document.getElementById("ba-sync-last-synced-badge");
	if (existingContainer) {
		existingContainer.remove();
	}
}

function formatRelativeTime(timestamp) {
	if (!timestamp) {
		return "";
	}

	const now = new Date();
	const syncDate = new Date(timestamp);

	if (isNaN(syncDate.getTime())) {
		return "Invalid date";
	}

	const diffMs = now.getTime() - syncDate.getTime();
	const diffSec = Math.floor(diffMs / 1000);
	const diffMin = Math.floor(diffSec / 60);
	const diffHours = Math.floor(diffMin / 60);
	const diffDays = Math.floor(diffHours / 24);
	const diffWeeks = Math.floor(diffDays / 7);

	if (diffSec < 60) {
		return "just now";
	} else if (diffMin < 60) {
		const mins = Math.max(1, diffMin);
		return `${mins} minute${mins > 1 ? "s" : ""} ago`;
	} else if (diffHours < 24) {
		return `${diffHours} hour${diffHours > 1 ? "s" : ""} ago`;
	} else if (diffDays < 7) {
		return `${diffDays} day${diffDays > 1 ? "s" : ""} ago`;
	} else if (diffWeeks < 4) {
		return `${diffWeeks} week${diffWeeks > 1 ? "s" : ""} ago`;
	} else {
		const months = Math.floor(diffDays / 30);
		if (months < 12) {
			return `${months} month${months > 1 ? "s" : ""} ago`;
		}
		const years = Math.floor(months / 12);
		return `${years} year${years > 1 ? "s" : ""} ago`;
	}
}
