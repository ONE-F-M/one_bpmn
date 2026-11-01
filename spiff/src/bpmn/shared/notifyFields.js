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

/**
 * get_email_fields as one list: own fields first, then linked fields labelled "Link label · Field label".
 * Only fields of the given types are kept.
 */
export function flattenEmailFields(result, fieldtypes) {
	const keep = (f) => fieldtypes.includes(f.fieldtype);
	const own = (result?.fields || []).filter(keep).map((f) => ({ ...f, linked: false }));
	const linked = (result?.linked || []).flatMap((group) =>
		group.fields.filter(keep).map((f) => ({ ...f, label: `${group.label} · ${f.label}`, linked: true }))
	);
	return [...own, ...linked];
}

/** Search box options: the doctype's fields, then a Linked documents group; fields in use are left out. */
export function fieldOptionGroups(fields, doctype, used) {
	const option = (f) => ({ label: f.label, value: f.fieldname });
	const free = fields.filter((f) => !used.includes(f.fieldname));
	return [
		{ group: `${doctype} fields`, items: free.filter((f) => !f.linked).map(option) },
		{ group: "Linked documents", items: free.filter((f) => f.linked).map(option) },
	].filter((g) => g.items.length);
}

/** The Arabic fields that can hold a field's Arabic value, with their labels. */
export function arabicCandidates(fields, fieldname) {
	const field = fields.find((f) => f.fieldname === fieldname);
	return (field?.arabic_candidates || []).map((name) => ({
		fieldname: name,
		label: fields.find((f) => f.fieldname === name)?.label || name,
	}));
}

/** The list with the entry for fieldname replaced. */
export function replaceEntry(list, fieldname, entry) {
	return list.map((e) => (fieldOf(e) === fieldname ? entry : e));
}
