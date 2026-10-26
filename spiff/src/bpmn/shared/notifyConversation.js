/**
 * notifyConversation holds the Conversation layout settings:
 * { actions: [{ key: "reply" | "note", completesWith }], internalNotes, canned: [HD Saved Reply names] }.
 * completesWith is the Task Action a reply or note also presses, or "" to leave the task open.
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
			? saved.actions
					.filter((a) => CONVERSATION_ACTIONS[a.key])
					.map((a) => ({ key: a.key, completesWith: typeof a.completesWith === "string" ? a.completesWith : "" }))
			: Object.keys(CONVERSATION_ACTIONS).map((key) => ({ key, completesWith: "" })),
		internalNotes: !!saved.internalNotes,
		canned: Array.isArray(saved.canned) ? saved.canned : [],
	};
}

/** The conversation action not yet on the list, or undefined when both are. */
export function missingConversationAction(actions) {
	return Object.keys(CONVERSATION_ACTIONS).find((key) => !actions.some((a) => a.key === key));
}
