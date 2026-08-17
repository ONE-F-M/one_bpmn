// Copyright (c) 2026, one-fm and contributors
// For license information, please see license.txt
//
// The triage path for one complaint, on the form the reviewer is already
// reading (WI-001641 / WI-001822). Without these buttons the conversion is an
// API call, which means it never happens: the person who can judge whether a
// thumbs-down is a real regression is not the person who opens a console.
//
// Three states, one action each:
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

frappe.ui.form.on("AI Response Feedback", {
	refresh(frm) {
		frm.clear_custom_buttons();
		if (frm.is_new()) return;

		const negative = frm.doc.rating === "Negative";

		if (negative && frm.doc.status === "New") {
			frm.add_custom_button(__("Mark Reviewed"), () => {
				frm.set_value("status", "Reviewed").then(() => frm.save());
			});
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

		if (negative && frm.doc.status === "New") {
			frm.dashboard.set_headline(
				__("Nobody has looked at this yet. Review it before turning it into a test.")
			);
		}
	},

	// Dismissing is the honest outcome for most negatives: an answer the user
	// disliked but which was correct is not a regression, and saying so is
	// useful information about the rating, not about the agent.
	status(frm) {
		frm.trigger("refresh");
	},
});

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
