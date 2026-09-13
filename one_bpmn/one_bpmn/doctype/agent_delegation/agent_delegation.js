// Copyright (c) 2026, one-fm and contributors
// For license information, please see license.txt
//
// The same two actions the Delegations screen offers, on the Desk form.
//
// Not a second implementation: both buttons call the endpoints that already own
// the rules, so the person-only check, the honest reporting of what could and
// could not be stopped, the attempt accounting and the unchanged-limit warning
// behave identically wherever they are triggered from. A copy of any of that
// here would be a second set of rules waiting to disagree with the first.

const CANCELLABLE = ["Delegated", "In Progress", "Needs Review"];
const REDELEGATABLE = ["Failed", "Needs Review", "Cancelled"];

frappe.ui.form.on("Agent Delegation", {
	refresh(frm) {
		if (frm.is_new()) return;

		if (CANCELLABLE.includes(frm.doc.status)) {
			frm.add_custom_button(
				__("Cancel Delegation"),
				() => cancel_delegation(frm),
				__("Delegation")
			);
		}

		// A delegation that STOPPED can be handed back. One still running cannot:
		// that would give two live runs for one piece of work. A completed one
		// cannot either — "run this again" is a different request.
		if (REDELEGATABLE.includes(frm.doc.status)) {
			frm.add_custom_button(
				__("Hand Back to Agent"),
				() => hand_back(frm, false),
				__("Delegation")
			);
		}

		frm.page.set_inner_btn_group_as_primary(__("Delegation"));

		if (frm.doc.stopped_reason) {
			frm.dashboard.set_headline(
				__("This delegation stopped: {0}. The work is not finished.", [
					frappe.utils.escape_html(frm.doc.stopped_reason),
				])
			);
		}
	},
});

function cancel_delegation(frm) {
	// A reason is optional but asked for every time: "why did somebody stop
	// this" is the question the record gets asked weeks later.
	const dialog = new frappe.ui.Dialog({
		title: __("Stop this delegation"),
		fields: [
			{
				fieldtype: "Small Text",
				fieldname: "reason",
				label: __("Why (optional)"),
				description: __(
					"The worker stops advancing, but a pass already running cannot be interrupted — you will be told which happened."
				),
			},
		],
		primary_action_label: __("Stop it"),
		primary_action: (values) => {
			dialog.hide();
			frappe.call({
				method: "one_bpmn.api.a2a_admin_api.cancel_delegation",
				args: { name: frm.doc.name, reason: values.reason || "" },
				freeze: true,
				freeze_message: __("Stopping the delegation…"),
				callback: (r) => {
					const out = r.message || {};
					frappe.msgprint({
						title: __("Delegation cancelled"),
						indicator: "orange",
						message: cancel_outcome_message(out),
					});
					frm.reload_doc();
				},
			});
		},
	});
	dialog.show();
}

function cancel_outcome_message(out) {
	// What actually happened, not a bare success. "The worker was stopped" and
	// "the worker had nothing running, so we stopped waiting" are different
	// outcomes and the person cancelling needs to know which they got.
	const lines = [frappe.utils.escape_html(out.detail || __("Cancelled."))];
	if (out.worker_stopped) {
		lines.push(
			__(
				"The worker will not advance any further. A pass already running when you cancelled may still finish — nothing can interrupt one mid-flight."
			)
		);
	} else {
		lines.push(__("The worker had no running process to stop, so the delegation stopped waiting."));
	}
	if (out.task_closed === false) {
		lines.push(
			__("Its task row could not be closed just now — the reconciler will settle it shortly.")
		);
	}
	if (out.caller_woken) lines.push(__("The agent waiting on it was woken."));
	return lines.join("<br><br>");
}

function hand_back(frm, acknowledged) {
	frappe.call({
		method: "one_bpmn.api.a2a_admin_api.redelegate_delegation",
		args: { name: frm.doc.name, acknowledged: acknowledged ? 1 : 0 },
		freeze: true,
		freeze_message: __("Handing the work back…"),
		callback: (r) => {
			const out = r.message || {};
			// Nothing has happened yet: the limit that stopped this has not moved,
			// so the person is told before anything runs. It never blocks — the
			// point of the action is that they have judged it — but it must not
			// silently walk into the same wall.
			if (out.state === "confirm") {
				frappe.confirm(
					`${frappe.utils.escape_html(out.warning)}<br><br>${__("Hand it back anyway?")}`,
					() => hand_back(frm, true)
				);
				return;
			}
			frappe.msgprint({
				title: __("Handed back to the agent"),
				indicator: out.state === "started" ? "green" : "orange",
				message: hand_back_message(out),
			});
			frm.reload_doc();
		},
	});
}

function hand_back_message(out) {
	const lines = [
		__("Attempt {0}, the {1} a person has asked for.", [out.attempt, out.by_a_person]),
		__(
			"It has {0} minute(s) this time — a hand-over starts the clock again, unlike an automatic retry.",
			[out.deadline_minutes]
		),
	];
	if (out.previous_run_retired) lines.push(__("The previous run was closed first."));
	if (out.state !== "started") {
		lines.push(__("The worker did not start — check the Error Log."));
	}
	return lines.join("<br><br>");
}
