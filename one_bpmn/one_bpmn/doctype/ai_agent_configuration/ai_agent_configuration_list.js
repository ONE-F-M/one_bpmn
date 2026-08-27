// Copyright (c) 2026, one-fm and contributors
// For license information, please see license.txt

frappe.listview_settings["AI Agent Configuration"] = {
	// Show lifecycle_status (not the default Enabled/Disabled) as the row
	// indicator. The colour comes from frappe.one_bpmn.lifecycle_color, the
	// same function the form header indicator uses (ai_agent_configuration.js)
	// — kept as the single source of truth so the two views can't drift.
	get_indicator(doc) {
		const status = doc.lifecycle_status || "Draft";
		return [
			__(status),
			frappe.one_bpmn.lifecycle_color(status),
			"lifecycle_status,=," + status,
		];
	},
};
