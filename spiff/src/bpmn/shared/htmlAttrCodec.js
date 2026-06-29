/**
 * HTML ↔ Base64 codec for BPMN XML attributes.
 *
 * BPMN XML attributes cannot safely contain raw HTML (e.g. `<p>Hello</p>`)
 * because the XML parser treats angle brackets as tag boundaries, causing
 * parse errors like "unparsable content </p> detected".
 *
 * These helpers encode HTML to URL-safe Base64 before writing it to
 * `spiffworkflow:*` attributes, and decode it back when reading.
 *
 * Used for:  notifyAssigneeBody, emailBody
 */

/**
 * Encode an HTML string to Base64 for safe storage in an XML attribute.
 * Returns `undefined` if the input is falsy (so the attribute is removed).
 */
export function encodeHtmlAttr(html) {
	if (!html) return undefined;
	try {
		// TextEncoder handles Unicode correctly
		const bytes = new TextEncoder().encode(html);
		let binary = "";
		for (let i = 0; i < bytes.length; i++) {
			binary += String.fromCharCode(bytes[i]);
		}
		return btoa(binary);
	} catch (_) {
		// Fallback: return raw (will likely break XML but better than silent loss)
		return html;
	}
}

/**
 * Decode a Base64-encoded HTML attribute back to its original HTML string.
 * Gracefully handles legacy values that were stored as raw HTML (not encoded).
 */
export function decodeHtmlAttr(encoded) {
	if (!encoded) return "";
	try {
		// Try Base64 decode first
		const binary = atob(encoded);
		const bytes = new Uint8Array(binary.length);
		for (let i = 0; i < binary.length; i++) {
			bytes[i] = binary.charCodeAt(i);
		}
		return new TextDecoder().decode(bytes);
	} catch (_) {
		// Not valid Base64 — assume it's a legacy raw HTML value
		return encoded;
	}
}
