// Prefer the server's own message over frappe-ui's "<url> <ExceptionClass>" fallback.
export function serverMessage(e) {
	const msgs = Array.isArray(e?.messages) ? e.messages.filter(Boolean) : [];
	const raw = msgs.join("\n") || e?.message || "Unknown error";
	return raw.replace(/<[^>]*>/g, "").trim();
}
