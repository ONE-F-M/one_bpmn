// Copyright (c) 2026, one-fm and contributors
// For license information, please see license.txt

frappe.listview_settings["AI Agent Configuration"] = {
	// Show lifecycle_status (not the default Enabled/Disabled) as the row
	// indicator. Colours mirror frappe.one_bpmn.lifecycle_color in the form JS.
	get_indicator(doc) {
		const color =
			{
				"Draft": "gray",
				"Validating": "orange",
				"Provisioning": "light-blue",
				"Evaluating": "purple",
				"Live": "green",
				"Needs Attention": "red",
				"Retired": "darkgrey",
			}[doc.lifecycle_status] || "gray";
		return [
			__(doc.lifecycle_status || "Draft"),
			color,
			"lifecycle_status,=," + (doc.lifecycle_status || "Draft"),
		];
	},
};
