/**
 * notifyConversation holds the Conversation layout settings:
 * { actions: [{ key: "reply" | "note", completes }], internalNotes, canned: [HD Saved Reply names] }.
 */
export const CONVERSATION_ACTIONS = {
	reply: { label: "Reply", detail: "Communication to the sender" },
	note: { label: "Add Note", detail: "Comment on the document" },
};

/** Saved settings, or Reply and Add Note with nothing else ticked. */
export function parseConversation(raw) {
	const saved = raw ? JSON.parse(raw) : {};
	return {
		actions: Array.isArray(saved.actions)
			? saved.actions.filter((a) => CONVERSATION_ACTIONS[a.key])
			: Object.keys(CONVERSATION_ACTIONS).map((key) => ({ key, completes: false })),
		internalNotes: !!saved.internalNotes,
		canned: Array.isArray(saved.canned) ? saved.canned : [],
	};
}

/** The conversation action not yet on the list, or undefined when both are. */
export function missingConversationAction(actions) {
	return Object.keys(CONVERSATION_ACTIONS).find((key) => !actions.some((a) => a.key === key));
}
