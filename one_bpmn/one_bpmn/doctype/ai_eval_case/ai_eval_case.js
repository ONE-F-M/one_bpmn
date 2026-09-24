// Copyright (c) 2026, one-fm and contributors
// For license information, please see license.txt

frappe.ui.form.on("AI Eval Case", {
	refresh(frm) {
		update_first_assertion_threshold(frm);
	},

	assertions_add(frm) {
		update_first_assertion_threshold(frm);
	},

	assertions_remove(frm) {
		update_first_assertion_threshold(frm);
	},

	assertions_move(frm) {
		update_first_assertion_threshold(frm);
	},
});

frappe.ui.form.on("AI Eval Assertion", {
	pass_threshold(frm) {
		update_first_assertion_threshold(frm);
	},

	assertion_type(frm) {
		update_first_assertion_threshold(frm);
	},
});

function update_first_assertion_threshold(frm) {
	if (!frm.doc.assertions || frm.doc.assertions.length === 0) {
		frm.set_df_property("first_assertion_pass_threshold", "hidden", true);
		return;
	}

	const first_assertion = frm.doc.assertions[0];
	let threshold_text = "";

	if (first_assertion.assertion_type === "llm_judge" && first_assertion.pass_threshold) {
		threshold_text = first_assertion.pass_threshold;
	}

	// Create the field if it doesn't exist
	if (!frm.get_field("first_assertion_pass_threshold")) {
		frm.add_custom_button_group = frm.add_custom_button_group || {};
		// Add a custom section to show the threshold near the top
		const field_found = frm.fields_dict.first_assertion_pass_threshold;
		if (!field_found) {
			// Field will be added through a custom HTML approach
			add_threshold_section(frm, threshold_text, first_assertion);
			return;
		}
	}

	// Update the field if it exists
	frm.set_value("first_assertion_pass_threshold", threshold_text || "");
	
	// Show/hide based on whether there's a value
	const show_field = first_assertion.assertion_type === "llm_judge" && first_assertion.pass_threshold;
	frm.set_df_property("first_assertion_pass_threshold", "hidden", !show_field);
}

function add_threshold_section(frm, threshold_text, first_assertion) {
	// This adds a summary section near the top of the form
	const section_id = "first_assertion_threshold_section";
	
	// Remove existing section if present
	const existing = frm.layout.form_layout.wrapper.find(`#${section_id}`);
	if (existing.length) {
		existing.remove();
	}

	if (first_assertion.assertion_type !== "llm_judge") {
		return;
	}

	const html = `
		<div id="${section_id}" class="form-column">
			<div class="form-section">
				<div class="form-section-head">
					<span class="indicator-pill blue ellipsis" title="First Assertion Pass Threshold">
						First Assertion Pass Threshold: <strong>${threshold_text || "—"}</strong>
					</span>
				</div>
			</div>
		</div>
	`;

	// Insert after the main title section
	frm.layout.form_layout.wrapper.find(".form-column").first().after(html);
}
