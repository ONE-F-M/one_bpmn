import { frappeGet } from "./frappeResource";

// A doctype's records, loaded once per page for every picker that lists them; add() keeps a created one.
export function cachedRecordList(doctype, fields) {
	let records = null;
	let loading = null;

	async function load() {
		loading ||= frappeGet(`/api/resource/${doctype}`, {
			fields: JSON.stringify(fields),
			limit_page_length: 0,
			order_by: "name asc",
		}).then((rows) => {
			records = Array.isArray(rows) ? rows : [];
		});
		try {
			await loading;
		} catch (err) {
			// A failed load is retried by the next picker that opens, not cached.
			loading = null;
			throw err;
		}
		return records;
	}

	function add(record) {
		records = [...(records || []), record];
	}

	return { load, add };
}
