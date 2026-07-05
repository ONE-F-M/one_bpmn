// Copyright (c) 2026, one-fm and contributors
// For license information, please see license.txt
//
// WI-001363 (5-03): "Create Eval Case" pre-fills an AI Eval Case from this
// run. Plain task runs pre-fill directly (fast path); subprocess runs
// (element_type="subprocess", WI-001358) prompt for which Step — and which
// tool call within it — to base the case on, since a subprocess run has no
// single input/output. Error runs are allowed too, not only Success.

frappe.ui.form.on("AI Agent Run", {
	refresh: function (frm) {
		if (frm.is_new()) return;

		frm.add_custom_button(__("Create Eval Case"), function () {
			_create_eval_case(frm);
		}, __("Actions"));
	},
});

async function _create_eval_case(frm) {
	if (!["Success", "Error"].includes(frm.doc.status)) {
		frappe.msgprint({
			title: __("Cannot Create Eval Case"),
			message: __("Only finished runs (Success or Error) can become eval cases."),
			indicator: "orange",
		});
		return;
	}

	if (frm.doc.element_type === "subprocess") {
		return _create_from_subprocess_run(frm);
	}

	// Plain task run: server factory pre-fills from the run + its Steps.
	frappe.dom.freeze(__("Creating eval case…"));
	try {
		const res = await frappe.call({
			method: "one_bpmn.agents.eval_case_factory.create_eval_case_from_run",
			args: { run_name: frm.doc.name },
		});
		frappe.dom.unfreeze();
		if (res && res.message) {
			frappe.set_route("Form", "AI Eval Case", res.message);
		}
	} catch (err) {
		frappe.dom.unfreeze();
		frappe.msgprint({
			title: __("Error"),
			message: __("Failed to create eval case: {0}", [(err && err.message) || err]),
			indicator: "red",
		});
	}
}

async function _create_from_subprocess_run(frm) {
	frappe.dom.freeze(__("Fetching run steps…"));
	let steps = [];
	try {
		const res = await frappe.call({
			method: "one_bpmn.agents.eval_case_factory.get_run_steps_for_case_picker",
			args: { run_name: frm.doc.name },
		});
		steps = (res && res.message) || [];
	} finally {
		frappe.dom.unfreeze();
	}

	if (!steps.length) {
		frappe.msgprint(__("This run has no steps to base a case on."));
		return;
	}

	// Build the Step options; a Step with >1 tool call needs a second choice.
	const step_options = steps.map((s) => ({
		label: `#${s.step_index} · ${s.role}` + (s.tool_calls.length ? ` (${s.tool_calls.length} tool call(s))` : ""),
		value: s.name,
	}));

	const dialog = new frappe.ui.Dialog({
		title: __("Create Eval Case from Subprocess Run"),
		fields: [
			{
				fieldname: "step",
				fieldtype: "Select",
				label: __("Step"),
				options: step_options.map((o) => o.label).join("\n"),
				reqd: 1,
			},
			{
				fieldname: "tool_call",
				fieldtype: "Select",
				label: __("Tool Call"),
				depends_on: "step",
				options: "",
			},
		],
		primary_action_label: __("Create"),
		primary_action(values) {
			const step = steps[step_options.findIndex((o) => o.label === values.step)];
			let tool_call_name = null;
			if (step && step.tool_calls.length) {
				const match = step.tool_calls.find((tc) => tc.tool_name === values.tool_call);
				tool_call_name = match ? match.name : step.tool_calls[0].name;
			}
			dialog.hide();
			_submit_subprocess_case(frm, step.name, tool_call_name);
		},
	});

	// Populate the Tool Call dropdown when a Step with multiple calls is chosen.
	dialog.fields_dict.step.$input.on("change", function () {
		const label = dialog.get_value("step");
		const step = steps[step_options.findIndex((o) => o.label === label)];
		const tool_field = dialog.fields_dict.tool_call;
		if (step && step.tool_calls.length > 1) {
			tool_field.df.options = step.tool_calls.map((tc) => tc.tool_name).join("\n");
			tool_field.df.hidden = 0;
		} else {
			tool_field.df.options = "";
			tool_field.df.hidden = 1;
		}
		tool_field.refresh();
	});

	dialog.show();
}

async function _submit_subprocess_case(frm, step_name, tool_call_name) {
	frappe.dom.freeze(__("Creating eval case…"));
	try {
		const res = await frappe.call({
			method: "one_bpmn.agents.eval_case_factory.create_eval_case_from_run",
			args: { run_name: frm.doc.name, step_name, tool_call_name },
		});
		frappe.dom.unfreeze();
		if (res && res.message) {
			frappe.set_route("Form", "AI Eval Case", res.message);
		}
	} catch (err) {
		frappe.dom.unfreeze();
		frappe.msgprint({
			title: __("Error"),
			message: __("Failed to create eval case: {0}", [(err && err.message) || err]),
			indicator: "red",
		});
	}
}
