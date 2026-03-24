/**
 * Shared BPMN download helpers.
 *
 * Centralised here so Editor.vue and Home.vue use identical sanitisation rules,
 * MIME type, and object-URL revocation timing.
 */

/**
 * Strip characters that are illegal in filenames across common OSes.
 * Falls back to "diagram" if the result would be empty.
 *
 * @param {string} name
 * @returns {string}
 */
export function sanitiseFilename(name) {
	return (name || "diagram").replace(/[/\\:*?"<>|]/g, "_").trim() || "diagram";
}

/**
 * Trigger a browser download of `xml` as a .bpmn file named after `title`.
 *
 * @param {string} xml   - BPMN XML content
 * @param {string} title - Human-readable diagram title (will be sanitised)
 */
export function downloadBpmn(xml, title) {
	const filename = sanitiseFilename(title) + ".bpmn";
	const blob = new Blob([xml], { type: "application/xml" });
	const url = URL.createObjectURL(blob);
	const link = document.createElement("a");
	link.href = url;
	link.download = filename;
	document.body.appendChild(link);
	link.click();
	document.body.removeChild(link);
	URL.revokeObjectURL(url);
	return filename;
}
