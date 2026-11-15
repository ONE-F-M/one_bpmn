// Copyright (c) 2026, ONE-F-M and contributors
// For license information, please see license.txt

const STATUS_DESCRIPTIONS = {
	"Draft": "The skill is still being written or tested. It can only be used by agents if they are explicitly configured to allow Draft skills.",
	"Active": "The skill is live and ready for production use by any agent.",
	"Deprecated": "The skill is retired and should no longer be used."
};

const TIER_DESCRIPTIONS = {
	"Draft-Only": "The skill is strictly sandboxed and cannot affect production data.",
	"Read-Only": "The skill is allowed to use tools that only read data, but cannot modify the database.",
	"Action-Allowed": "The skill is permitted to use tools that modify data or trigger external systems."
};

frappe.ui.form.on("AI Skill", {
	setup(frm) {
		// Fetch divisor from settings once when form loads
		frappe.db.get_single_value("Processa Settings", "token_estimator_chars_per_token")
			.then(value => {
				frm.token_divisor = value || 4;
			});
	},
	refresh(frm) {
		update_status_description(frm);
		update_tier_description(frm);
		
		// Attempt to bind to keystrokes on the body wrapper
		let body_field = frm.fields_dict.body;
		if (body_field && body_field.$wrapper) {
			body_field.$wrapper.on('keyup', frappe.utils.debounce(() => {
				calculate_token_estimate(frm);
			}, 300));
		}
	},
	body(frm) {
		calculate_token_estimate(frm);
	},
	status(frm) {
		update_status_description(frm);
	},
	tier(frm) {
		update_tier_description(frm);
	}
});

function calculate_token_estimate(frm) {
	let text = frm.fields_dict.body.get_value() || "";
	let divisor = frm.token_divisor || 4;
	let estimate = Math.floor(text.length / divisor);
	
	if (frm.doc.token_estimate !== estimate) {
		frm.set_value('token_estimate', estimate);
	}
}

function update_status_description(frm) {
	if (frm.doc.status && STATUS_DESCRIPTIONS[frm.doc.status]) {
		frm.set_df_property('status', 'description', STATUS_DESCRIPTIONS[frm.doc.status]);
	} else {
		frm.set_df_property('status', 'description', '');
	}
}

function update_tier_description(frm) {
	if (frm.doc.tier && TIER_DESCRIPTIONS[frm.doc.tier]) {
		frm.set_df_property('tier', 'description', TIER_DESCRIPTIONS[frm.doc.tier]);
	} else {
		frm.set_df_property('tier', 'description', '');
	}
}
