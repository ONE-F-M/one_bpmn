/**
 * notifyConversation holds the Conversation layout settings:
 * { actions: [{ key: "reply" | "note", label }], internalNotes, canned: [HD Saved Reply names] }.
 * label is the button text the email shows for the action.
 */
export const CONVERSATION_ACTIONS = {
	reply: { label: "Reply", detail: "Message to the sender" },
	note: { label: "Add Note", detail: "Internal note on the document" },
};

/** Saved settings, or Reply and Add Note with nothing else ticked. */
export function parseConversation(raw) {
	const saved = raw ? JSON.parse(raw) : {};
	return {
		actions: Array.isArray(saved.actions)
			? saved.actions
					.filter((a) => CONVERSATION_ACTIONS[a.key])
					.map((a) => ({ key: a.key, label: labelOf(a) }))
			: Object.keys(CONVERSATION_ACTIONS).map((key) => ({ key, label: CONVERSATION_ACTIONS[key].label })),
		internalNotes: !!saved.internalNotes,
		canned: Array.isArray(saved.canned) ? saved.canned : [],
	};
}

function labelOf(action) {
	const label = typeof action.label === "string" ? action.label.trim() : "";
	return label || CONVERSATION_ACTIONS[action.key].label;
}

/** The conversation action not yet on the list, or undefined when both are. */
export function missingConversationAction(actions) {
	return Object.keys(CONVERSATION_ACTIONS).find((key) => !actions.some((a) => a.key === key));
}
