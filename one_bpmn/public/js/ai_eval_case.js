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
		remove_threshold_section(frm);
		return;
	}

	const first_assertion = frm.doc.assertions[0];

	if (first_assertion.assertion_type === "llm_judge" && first_assertion.pass_threshold) {
		show_threshold_section(frm, first_assertion.pass_threshold);
	} else {
		remove_threshold_section(frm);
	}
}

function show_threshold_section(frm, threshold_value) {
	const section_id = "first_assertion_threshold_section";
	
	// Remove existing section if present
	const existing = frm.layout.form_layout.wrapper.find(`#${section_id}`);
	if (existing.length) {
		existing.remove();
	}

	const html = `
		<div id="${section_id}" class="form-column" style="margin-bottom: 1rem;">
			<div class="form-section">
				<h6 style="margin-bottom: 0.5rem; color: var(--text-muted);">First Assertion Pass Threshold</h6>
				<div style="padding: 0.75rem; background: var(--bg-light); border-left: 3px solid var(--primary); border-radius: 0.25rem;">
					<strong style="font-size: 1.1rem; color: var(--primary);">${frappe.utils.html_escape(threshold_value.toString())}</strong>
				</div>
			</div>
		</div>
	`;

	// Insert after the expected_output field
	const insert_after = frm.layout.form_layout.wrapper.find("[data-fieldname='expected_output']").closest(".form-column");
	if (insert_after.length) {
		insert_after.after(html);
	} else {
		// Fallback: insert at the beginning of the form
		frm.layout.form_layout.wrapper.find(".form-layout").prepend(html);
	}
}

function remove_threshold_section(frm) {
	frm.layout.form_layout.wrapper.find("#first_assertion_threshold_section").remove();
}
