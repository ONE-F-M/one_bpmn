// Copyright (c) 2026, one-fm and contributors
// For license information, please see license.txt

frappe.ui.form.on("AI Memory", {
	refresh: function (frm) {
		// Scope-specific fields (agent_element / process / reference_*) are shown
		// and made mandatory via depends_on / mandatory_depends_on in the DocType.
	},
});
