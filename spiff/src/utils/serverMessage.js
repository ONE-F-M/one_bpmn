// frappe-ui falls back to "<url> <ExceptionClass>" when it finds no friendlier
// text, so prefer the server's own message.
export function serverMessage(e) {
	const msgs = Array.isArray(e?.messages) ? e.messages.filter(Boolean) : [];
	const raw = msgs.join("\n") || e?.message || "Unknown error";
	return raw.replace(/<[^>]*>/g, "").trim();
}
