// Copyright (c) 2026, one-fm and contributors
// For license information, please see license.txt

frappe.ui.form.on("AI Agent Run", {
	refresh: function (frm) {
		if (!frm.is_new()) {
			frm.add_custom_button(__("Create Eval Case"), function () {
				create_eval_case(frm);
			});
		}
	},
});

/**
 * Create an AI Eval Case from the current AI Agent Run.
 *
 * - Blocks runs with status != "Success".
 * - Fetches AI Agent Steps to extract system, user, and assistant prompts.
 * - Looks up process_model from the linked instance.
 * - Opens a pre-filled AI Eval Case form via frappe.new_doc.
 */
function create_eval_case(frm) {
	if (frm.doc.status !== "Success") {
		frappe.msgprint(__("Cannot create eval case from a failed run"));
		return;
	}

	frappe.call({
		method: "frappe.client.get_list",
		args: {
			doctype: "AI Agent Step",
			filters: { run: frm.doc.name },
			fields: ["role", "content"],
			order_by: "step_index asc",
		},
		freeze: true,
		freeze_message: __("Fetching run steps…"),
		callback: function (r) {
			if (!r || !r.message) {
				frappe.msgprint(__("No steps found for this run."));
				return;
			}

			var steps = r.message;
			var system_prompt = "";
			var user_prompt = "";
			var assistant_output = "";

			for (var i = 0; i < steps.length; i++) {
				if (steps[i].role === "system") {
					system_prompt = steps[i].content || "";
				} else if (steps[i].role === "user") {
					user_prompt = steps[i].content || "";
				} else if (steps[i].role === "assistant") {
					assistant_output = steps[i].content || "";
				}
			}

			var eval_case_values = {
				source_run: frm.doc.name,
				provider: frm.doc.provider,
				model: frm.doc.model,
				backend: frm.doc.backend,
				bpmn_id: frm.doc.bpmn_id,
				input_system_prompt: system_prompt,
				input_user_prompt: user_prompt,
				expected_output: assistant_output,
				title: "Eval from " + frm.doc.name,
			};

			// Look up process_model from the linked instance
			if (frm.doc.instance) {
				frappe.db.get_value(
					"BPMN Process Instance",
					frm.doc.instance,
					"process_model",
					function (value) {
						if (value && value.process_model) {
							eval_case_values.process_model = value.process_model;
						}
						frappe.new_doc("AI Eval Case", eval_case_values);
					}
				);
			} else {
				frappe.new_doc("AI Eval Case", eval_case_values);
			}
		},
	});
}
