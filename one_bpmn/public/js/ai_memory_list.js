// Copyright (c) 2026, one-fm and contributors
// For license information, please see license.txt
//
// Purge button for the AI Memory list view, mirroring the memory browser's
// Purge action (spiff/src/views/Memory.vue): confirm first, call the same
// purge_memories endpoint, then show the count removed and reload the list.
// Nothing is deleted until the confirmation is accepted.

frappe.listview_settings["AI Memory"] = {
	onload(listview) {
		listview.page.add_inner_button(__("Purge"), () => {
			const filters = listview.get_filters_for_args ? listview.get_filters_for_args() : listview.filter_area.get();
			const user_filter = (filters || []).find((f) => f[1] === "user");
			const target = user_filter ? user_filter[3] : null;
			const label = target && target !== "Shared" ? target : __("you");

			frappe.confirm(
				__(
					"This will permanently delete all memories for {0}. Shared memories are not touched. This cannot be undone.",
					[`<strong>${frappe.utils.escape_html(label)}</strong>`]
				),
				() => {
					frappe.call({
						method: "one_bpmn.api.memory_api.purge_memories",
						args: target && target !== "Shared" ? { user: target } : {},
						freeze: true,
						freeze_message: __("Purging\u2026"),
						callback: (r) => {
							const out = r.message || {};
							frappe.show_alert({
								message: __("Purged: {0} memor{1} removed.", [
									out.deleted,
									out.deleted === 1 ? "y" : "ies",
								]),
								indicator: "green",
							});
							listview.refresh();
						},
						error: () => {
							// frappe.call already surfaces the server's error message;
							// the list is left exactly as it was.
						},
					});
				}
			);
		});
	},
};
