// Records whose name contains the query, and whether the typed name is new enough to offer creating it.
export function filterRecords(records, query) {
	const q = (query || "").trim().toLowerCase();
	const matches = q ? records.filter((r) => r.name.toLowerCase().includes(q)) : records;
	return { matches, canCreate: !!q && !records.some((r) => r.name.toLowerCase() === q) };
}
