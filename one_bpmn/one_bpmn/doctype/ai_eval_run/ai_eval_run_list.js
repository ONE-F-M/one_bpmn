// Copyright (c) 2026, one-fm and contributors
// For license information, please see license.txt

frappe.listview_settings["AI Eval Run"] = {
	// Colour-code the run's status as the row indicator.
	get_indicator(doc) {
		const color =
			{
				"Running": "orange",
				"Passed": "green",
				"Failed": "red",
				"Error": "darkgrey",
			}[doc.status] || "gray";
		return [
			__(doc.status || "Running"),
			color,
			"status,=," + (doc.status || "Running"),
		];
	},
};
