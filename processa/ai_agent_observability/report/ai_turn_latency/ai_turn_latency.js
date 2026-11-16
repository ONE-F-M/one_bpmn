frappe.query_reports["AI Turn Latency"] = {
	filters: [
		{
			fieldname: "agent_configuration",
			label: __("Agent"),
			fieldtype: "Link",
			options: "AI Agent Configuration",
			reqd: 1,
		},
		{
			fieldname: "runs",
			label: __("Last N Runs"),
			fieldtype: "Int",
			default: 20,
		},
		{
			fieldname: "origin",
			label: __("Origin"),
			fieldtype: "Select",
			options: ["", "production", "eval"],
		},
	],
	tree: true,
	initial_depth: 0,
};
