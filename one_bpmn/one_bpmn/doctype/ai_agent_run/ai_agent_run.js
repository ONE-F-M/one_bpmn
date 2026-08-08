// Copyright (c) 2026, one-fm and contributors
// For license information, please see license.txt

frappe.ui.form.on("AI Agent Run", {
	refresh: function (frm) {
		if (frm.is_new()) return;

		frm.add_custom_button(__("Create Eval Case"), function () {
			_create_eval_case(frm);
		}, __("Actions"));
	},
});

/**
 * Create an AI Eval Case pre-filled from this AI Agent Run.
 * Only allowed on runs with status=Success.
 */
async function _create_eval_case(frm) {
	if (frm.doc.status !== "Success") {
		frappe.msgprint({
			title: __("Cannot Create Eval Case"),
			message: __("Cannot create eval case from a failed run"),
			indicator: "orange",
		});
		return;
	}

	frappe.dom.freeze(__("Fetching run steps…"));

	try {
		// Fetch the steps for this run, ordered by step_index
		const steps = await frappe.call({
			method: "frappe.client.get_list",
			args: {
				doctype: "AI Agent Step",
				filters: { run: frm.doc.name },
				fields: ["role", "content"],
				order_by: "step_index asc",
				limit_page_length: 0,
			},
		});

		const step_list = (steps && steps.message) ? steps.message : [];

		// Extract prompts by role
		let system_prompt = "";
		let user_prompt = "";
		let assistant_output = "";

		for (const step of step_list) {
			if (step.role === "system" && !system_prompt) {
				system_prompt = step.content || "";
			} else if (step.role === "user" && !user_prompt) {
				user_prompt = step.content || "";
			} else if (step.role === "assistant" && !assistant_output) {
				assistant_output = step.content || "";
			}
		}

		// Look up process_model from the linked BPMN Process Instance
		let process_model = "";
		if (frm.doc.instance) {
			const instance_data = await frappe.db.get_value(
				"BPMN Process Instance",
				frm.doc.instance,
				"process_model"
			);
			if (instance_data && instance_data.message) {
				process_model = instance_data.message.process_model || "";
			}
		}

		frappe.dom.unfreeze();

		// Open a new AI Eval Case form pre-filled with the run data
		frappe.new_doc("AI Eval Case", {
			title: "Eval from " + frm.doc.name,
			source_run: frm.doc.name,
			provider: frm.doc.provider,
			model: frm.doc.model,
			backend: frm.doc.backend,
			bpmn_id: frm.doc.bpmn_id,
			process_model: process_model,
			input_system_prompt: system_prompt,
			input_user_prompt: user_prompt,
			expected_output: assistant_output,
		});
	} catch (err) {
		frappe.dom.unfreeze();
		frappe.msgprint({
			title: __("Error"),
			message: __("Failed to fetch run steps: {0}", [err.message || err]),
			indicator: "red",
		});
	}
}
