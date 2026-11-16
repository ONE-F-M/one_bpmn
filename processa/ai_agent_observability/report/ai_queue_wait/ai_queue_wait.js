frappe.query_reports["AI Queue Wait"] = {
	filters: [
		{
			fieldname: "days",
			label: __("Last N Days"),
			fieldtype: "Int",
			default: 7,
		},
		{
			fieldname: "origin",
			label: __("Origin"),
			fieldtype: "Select",
			options: ["", "production", "eval"],
			default: "production",
		},
	],
};
