/**
 * notifyFacts and notifyDetails hold JSON lists of fields in the picked order. An entry is
 * a fieldname, or [fieldname, arabic_fieldname] once an Arabic field is picked for it.
 */
export const MAX_FACTS = 6;

/** The fieldname of a list entry. */
export const fieldOf = (entry) => (Array.isArray(entry) ? entry[0] : entry);

export function parseFieldList(raw) {
	return raw ? JSON.parse(raw) : [];
}

/** The attribute value: empty for an empty list. */
export function serializeFieldList(list) {
	return list.length ? JSON.stringify(list) : "";
}

/** The count on the Fields tab; Conversation has no Details. */
export function fieldsTabCount(facts, details, layout) {
	return facts.length + (layout === "chat" ? 0 : details.length);
}
