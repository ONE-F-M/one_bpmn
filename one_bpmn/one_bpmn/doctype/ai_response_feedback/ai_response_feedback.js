// Copyright (c) 2026, one-fm and contributors
// For license information, please see license.txt
//
// The triage path for one complaint, on the form the reviewer is already
// reading (WI-001641 / WI-001822). Without these buttons the conversion is an
// API call, which means it never happens: the person who can judge whether a
// thumbs-down is a real regression is not the person who opens a console.
//
//   Negative + New       → "Mark Reviewed"      (a person has looked at it)
//   Negative + Reviewed  → "Create Eval Case"   (this failure becomes a test)
//   anything + Converted → "Open Eval Case"     (go and write the expectation)
//
// The gap between New and Reviewed is the whole guard. People press thumbs down
// because a reply was slow, or because they disagreed with a correct answer —
// converting the raw stream would fill the suite with noise and destroy trust in
// it. So the button that creates a test is only ever available after someone has
// said "yes, this one".
//
// Every record now also has an AI Response Feedback Handling BPMN process
// running behind it, assigning "Review Feedback"/"Investigate & Fix" to the
// resolved Process Owner. Completing that real engine task — not just saving
// the status field — is what actually advances the process (notifies the
// rater, etc.); a plain status save would leave it waiting on that task
// forever. So refresh() asks the backend whether a task is waiting on the
// CURRENT user first, and only falls back to the old direct "Mark Reviewed"
// save when there genuinely is none (e.g. no Process Owner was resolved for
// this reply's agent).

frappe.ui.form.on("AI Response Feedback", {
	refresh(frm) {
		frm.clear_custom_buttons();
		if (frm.is_new()) return;

		frappe.call({
			method: "one_bpmn.api.feedback.get_my_pending_task",
			args: { feedback: frm.doc.name },
			callback(r) {
				render_buttons(frm, r.message || null);
			},
		});
	},

	// Dismissing is the honest outcome for most negatives: an answer the user
	// disliked but which was correct is not a regression, and saying so is
	// useful information about the rating, not about the agent.
	status(frm) {
		frm.trigger("refresh");
	},
});

function render_buttons(frm, pending_task) {
	const negative = frm.doc.rating === "Negative";
	const has_pending_task = pending_task && pending_task.actions && pending_task.actions.length;

	if (has_pending_task) {
		pending_task.actions.forEach((action) => {
			frm.add_custom_button(__(action), () =>
				complete_pending_task(frm, pending_task, action)
			).addClass("btn-primary");
		});
		frm.dashboard.set_headline(
			__('A process task ("{0}") is waiting on you for this feedback.', [pending_task.task_name])
		);
	} else if (negative && frm.doc.status === "New") {
		// No BPMN task is waiting on this user — either nothing is running
		// (no Process Owner resolved) or it's assigned to someone else. The
		// manual path stays as the honest fallback, same as before this
		// record ever had a process behind it.
		frm.add_custom_button(__("Mark Reviewed"), () => {
			frm.set_value("status", "Reviewed").then(() => frm.save());
		});
		frm.dashboard.set_headline(
			__("Nobody has looked at this yet. Review it before turning it into a test.")
		);
	}

	if (negative && frm.doc.status === "Reviewed" && !frm.doc.eval_case) {
		frm.add_custom_button(__("Create Eval Case"), () => create_case(frm)).addClass(
			"btn-primary"
		);
	}

	if (frm.doc.eval_case) {
		frm.add_custom_button(__("Open Eval Case"), () => {
			frappe.set_route("Form", "AI Eval Case", frm.doc.eval_case);
		});
	}
}

function complete_pending_task(frm, pending_task, action) {
	frappe.call({
		method: "one_bpmn.api.instance_api.complete_task",
		args: {
			instance_name: pending_task.instance,
			task_id: pending_task.task_id,
			data: JSON.stringify({ action }),
		},
		freeze: true,
		freeze_message: __("Completing…"),
		callback() {
			frm.reload_doc();
		},
	});
}

function create_case(frm) {
	// The suite is deliberately not asked for. Leaving it unset files the case in
	// the agent's own regression suite, created on first use — and never in the
	// provisioned "<agent> — Baseline" suite, whose cases are deleted every time
	// the agent is re-provisioned.
	frappe.call({
		method: "one_bpmn.api.feedback.create_eval_case_from_feedback",
		args: { feedback: frm.doc.name },
		freeze: true,
		freeze_message: __("Building the test case…"),
		callback(r) {
			const out = r.message || {};
			if (!out.eval_case) return;
			frappe.show_alert(
				{
					message: out.created
						? __("Eval case created. Write what should have happened.")
						: __("This complaint already has an eval case."),
					indicator: "green",
				},
				7
			);
			frm.reload_doc().then(() => frappe.set_route("Form", "AI Eval Case", out.eval_case));
		},
	});
}
