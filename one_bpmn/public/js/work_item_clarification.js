// Copyright (c) 2026, one-fm and contributors
// For license information, please see license.txt
//
// WI-002050: an agent's question, on the story it is about.
//
// The pending question is technically a task on a process instance, but the
// person who can settle it is the one who wrote the story — and asking them to
// open a process instance to unblock their own work item means asking them to
// learn the machinery first. So the question is shown here, and answered here.
//
// Answering routes through the endpoint that routes through the normal task
// completion, so nothing about permissions or resuming the agent behaves
// differently from answering it anywhere else.

frappe.ui.form.on("Work Item", {
	refresh(frm) {
		if (frm.is_new()) return;
		load_clarifications(frm);
	},
});

function load_clarifications(frm) {
	frappe.call({
		method: "one_bpmn.api.clarification_api.pending_for_document",
		args: { reference_doctype: "Work Item", reference_name: frm.doc.name },
		callback: (r) => {
			const data = (r && r.message) || {};
			render(frm, data.pending, data.history || []);
		},
	});
}

function render(frm, pending, history) {
	if (!pending && !history.length) return;

	if (pending) {
		// Deliberately loud. An agent that has stopped and is waiting is not a
		// background detail — nothing moves on this story until it is answered,
		// and the commonest failure of this whole pattern is a question nobody
		// notices.
		const waiting = pending.escalated_at
			? __("This has been escalated — it is still waiting.")
			: pending.reminded_at
			? __("A reminder has already gone out.")
			: "";

		frm.dashboard.clear_headline();
		frm.dashboard.set_headline(
			`<b>${frappe.utils.escape_html(pending.agent_configuration || __("An agent"))} ${__(
				"is waiting on you"
			)}</b> &nbsp; ${frappe.utils.escape_html(waiting)}`,
			"orange"
		);

		frm.dashboard.add_section(
			`<div style="padding:4px 0">
				<div style="white-space:pre-wrap">${frappe.utils.escape_html(pending.question || "")}</div>
				${
					pending.interpretations
						? `<div style="margin-top:6px;color:var(--text-muted)"><i>${__(
								"Choosing between"
						  )}:</i> ${frappe.utils.escape_html(pending.interpretations)}</div>`
						: ""
				}
				<div style="margin-top:6px;color:var(--text-muted);font-size:11px">
					${__("Round {0} · asked {1}", [
						pending.round || 1,
						frappe.datetime.comment_when(pending.asked_at),
					])}
				</div>
			</div>`,
			__("A question about this story")
		);

		if (pending.can_answer) {
			frm.page.set_primary_action(__("Answer the agent"), () => answer(frm, pending));
		} else {
			// Shown rather than hidden: knowing it is blocked on somebody else is
			// more useful than a button that refuses.
			frm.dashboard.set_headline(
				`<b>${__("Waiting on")} ${frappe.utils.escape_html(
					pending.owner_asked || __("the story owner")
				)}</b> — ${__("only the person asked can answer this.")}`,
				"orange"
			);
		}
	}

	if (history.length) {
		const rows = history
			.map(
				(h) => `<div style="margin-bottom:8px">
					<div><b>${__("Asked")}:</b> ${frappe.utils.escape_html(h.question || "")}</div>
					<div><b>${__("Answered")}:</b> ${frappe.utils.escape_html(h.answer || "—")}</div>
					<div style="color:var(--text-muted);font-size:11px">
						${frappe.utils.escape_html(h.answered_by || "")}
						${h.answered_at ? "· " + frappe.datetime.str_to_user(h.answered_at) : ""}
					</div>
				</div>`
			)
			.join("");
		frm.dashboard.add_section(rows, __("Questions already answered"));
	}
}

function answer(frm, pending) {
	const dialog = new frappe.ui.Dialog({
		title: __("Answer the agent"),
		fields: [
			{
				fieldtype: "HTML",
				options: `<div style="margin-bottom:8px;white-space:pre-wrap">${frappe.utils.escape_html(
					pending.question || ""
				)}</div>${
					pending.interpretations
						? `<div style="color:var(--text-muted)"><i>${__(
								"Choosing between"
						  )}:</i> ${frappe.utils.escape_html(pending.interpretations)}</div>`
						: ""
				}`,
			},
			{
				fieldtype: "Small Text",
				fieldname: "text",
				label: __("Your answer"),
				reqd: 1,
				description: __(
					"Say which reading is right, or give the missing detail. If this does not settle it the agent will ask again rather than guess."
				),
			},
		],
		primary_action_label: __("Send and let it continue"),
		primary_action: (values) => {
			dialog.hide();
			frappe.call({
				method: "one_bpmn.api.clarification_api.answer",
				args: { name: pending.name, text: values.text },
				freeze: true,
				freeze_message: __("Sending your answer…"),
				callback: () => {
					frappe.show_alert({
						message: __("Answered — the agent has picked up from where it paused."),
						indicator: "green",
					});
					frm.reload_doc();
				},
			});
		},
	});
	dialog.show();
}
