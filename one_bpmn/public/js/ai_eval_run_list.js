// Copyright (c) 2026, one-fm and contributors
// For license information, please see license.txt

frappe.listview_settings["AI Eval Run"] = {
	// Show status as the row indicator with colour-coded states
	get_indicator(doc) {
		const color =
			{
				"Running": "blue",
				"Passed": "green",
				"Failed": "red",
				"Error": "orange",
			}[doc.status] || "gray";
		return [
			__(doc.status || "Running"),
			color,
			"status,=," + (doc.status || "Running"),
		];
	},
};
