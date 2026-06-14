// Copyright (c) 2025, One BPMN and contributors
// For license information, please see license.txt

frappe.ui.form.on("Processa Settings", {
	refresh(frm) {
		// Add "Sync Now" button when BA sync is enabled
		if (frm.doc.enable_ba_sync) {
			frm.add_custom_button(__("Sync Now"), function () {
				frappe.confirm(
					__("This will pull Custom DocTypes, Custom Fields, and Property Setters from the BA site and apply them to this site. Continue?"),
					function () {
						frappe.call({
							method: "one_bpmn.api.schema_sync.trigger_manual_sync",
							freeze: true,
							freeze_message: __("Queuing schema sync..."),
							callback: function (r) {
								if (r.message) {
									frappe.show_alert({
										message: __(r.message.message),
										indicator: "blue",
									});
									// Open Schema Sync Log list after a brief delay
									setTimeout(function () {
										frappe.set_route("List", "Schema Sync Log");
									}, 1500);
								}
							},
							error: function () {
								frappe.show_alert({
									message: __("Failed to queue sync. Check Error Log for details."),
									indicator: "red",
								});
							},
						});
					}
				);
			}, __("BA Sync"));

			// Add shortcut to view sync logs
			frm.add_custom_button(__("View Sync Logs"), function () {
				frappe.set_route("List", "Schema Sync Log");
			}, __("BA Sync"));
		}

		// Show last sync time info
		if (frm.doc.last_sync_time) {
			frm.dashboard.set_headline(
				__("Last synced: {0}", [frappe.datetime.prettyDate(frm.doc.last_sync_time)])
			);
		} else if (frm.doc.enable_ba_sync) {
			frm.dashboard.set_headline(
				__("No sync has been run yet. The first sync will pull ALL records from BA.")
			);
		}
	},
});
