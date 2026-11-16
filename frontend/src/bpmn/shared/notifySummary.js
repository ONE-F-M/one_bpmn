import { isHtmlMode } from "./notifyAssigneeAttrs.js";
import { DEFAULT_TOKEN_HOURS, mergeNotifyActions } from "./notifyActions.js";
import { fieldOf } from "./notifyFields.js";

const LAYOUT_LABELS = { card: "Decision card", steps: "Step by step", chat: "Conversation" };

const parse = (raw, fallback) => (raw ? JSON.parse(raw) : fallback);

/**
 * What the panel shows under Launch Editor: a line, read-only rows and whether the
 * configured badge shows. values holds the notify attributes; body is decoded HTML.
 */
export function notifySummary(values, taskActions, fieldLabels = {}) {
	const label = (fieldname) => fieldLabels[fieldname] || fieldname;
	const subject = values.notifyAssigneeSubject || "";

	if (isHtmlMode(values.notifyLayout)) {
		const body = values.notifyAssigneeBody || "";
		const template = values.notifyAssigneeTemplate;
		return {
			line: template ? `Template attached: ${template}` : "Custom HTML body",
			rows: [
				{ k: "Body", v: template ? `Email Template ${template}` : `Custom HTML (${body.length} characters)` },
				{ k: "Subject", v: subject },
				{ k: "Buttons", v: "As today: first action filled; Confirm and Sign open ERPNext" },
			],
			configured: !!body.trim(),
		};
	}

	const isChat = values.notifyLayout === "chat";
	const facts = parse(values.notifyFacts, []).map((e) => label(fieldOf(e)));
	const details = parse(values.notifyDetails, []).map((e) => label(fieldOf(e)));
	const actions = mergeNotifyActions(taskActions, values.notifyActions);
	const primary = Object.keys(actions).find((name) => actions[name].primary);
	const asking = Object.entries(actions).filter(([, a]) => a.reason);
	const missingField = asking.some(([, a]) => !a.reasonField);
	const internalNotes = parse(values.notifyConversation, {}).internalNotes;

	return {
		line: `Layout: ${LAYOUT_LABELS[values.notifyLayout]}`,
		rows: [
			{ k: "Layout", v: LAYOUT_LABELS[values.notifyLayout] },
			{ k: "Subject", v: subject },
			{ k: isChat ? "Summary" : "Key facts", v: facts.join(", ") || "None picked", warn: !facts.length },
			{ k: "Details", v: isChat ? (internalNotes ? "Thread with internal notes" : "Thread") : details.join(", ") || "None" },
			{ k: "Primary", v: primary || "None" },
			{ k: "Buttons work for", v: `${values.notifyTokenHours || DEFAULT_TOKEN_HOURS} hours` },
			{
				k: "Reasons",
				v: asking.map(([name, a]) => `${name} to ${a.reasonField ? label(a.reasonField) : "no field"}`).join(", ")
					|| "No action asks for a reason",
				warn: missingField,
			},
		],
		configured: !missingField,
	};
}
