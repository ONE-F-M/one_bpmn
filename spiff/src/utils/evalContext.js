// Earlier turns and saved state a mid-conversation eval case starts from.

export const SEED_MESSAGE_TYPES = ["User", "Bot", "Tool"]

export const EXAMPLE_CONTEXT = JSON.stringify(
	{
		conversation_messages: [
			{ message_type: "User", text: "analyse the topology for this process" },
			{ message_type: "Bot", text: "I propose 2 processes: Visa Request and Visa Renewal. Does this topology look right?" },
		],
		session_state: {},
	},
	null,
	2,
)

// An error message for the text, or "" when the case can start from it.
export function midConversationError(text) {
	const trimmed = (text || "").trim()
	if (!trimmed) return "Add the earlier conversation, or untick Starts mid-conversation."
	let parsed
	try {
		parsed = JSON.parse(trimmed)
	} catch {
		return "The earlier conversation is not valid JSON."
	}
	if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
		return "The earlier conversation must be a JSON object with conversation_messages and, optionally, session_state."
	}
	const messages = parsed.conversation_messages
	if (messages !== undefined && !Array.isArray(messages)) return "conversation_messages must be a list."
	const bad = (messages || []).findIndex((m) => !m || !SEED_MESSAGE_TYPES.includes(m.message_type))
	if (bad !== -1) return `Message ${bad + 1} needs a message_type of User, Bot or Tool.`
	if (parsed.session_state !== undefined && (typeof parsed.session_state !== "object" || Array.isArray(parsed.session_state))) {
		return "session_state must be a JSON object."
	}
	return ""
}

// The earlier turns as { role, text } for display; Tool rows are saved state, not chat.
export function earlierTurns(context) {
	return ((context && context.conversation_messages) || [])
		.filter((m) => m.message_type === "User" || m.message_type === "Bot")
		.map((m) => ({ role: m.message_type, text: m.text || "" }))
}

// Saved state the agent starts with: Tool rows' metadata and the session_state.
export function savedState(context) {
	if (!context) return null
	const tools = (context.conversation_messages || []).filter((m) => m.message_type === "Tool" && m.metadata)
	const session = context.session_state && Object.keys(context.session_state).length ? context.session_state : null
	if (!tools.length && !session) return null
	return {
		...(tools.length ? { migration_context: tools.map((m) => (typeof m.metadata === "string" ? JSON.parse(m.metadata) : m.metadata)) } : {}),
		...(session ? { session_state: session } : {}),
	}
}
