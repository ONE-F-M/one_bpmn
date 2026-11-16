export const SEARCH_DELAY = 300;

export function toOptions(rows, valueField = "name", renderOption) {
	return (rows || [])
		.map((row) => {
			const value = row[valueField] || row.name;
			return {
				label: renderOption ? renderOption(row) : row.label || value,
				value,
				style: row.style,
				raw: row,
			};
		})
		.filter((option) => option.value);
}

export function splitValues(csv) {
	return csv
		? csv
				.split(",")
				.map((v) => v.trim())
				.filter(Boolean)
		: [];
}

export function joinValues(values) {
	return (values || []).join(",");
}

export function valuesOf(selection) {
	const list = Array.isArray(selection) ? selection : selection ? [selection] : [];
	return list.map((item) => (typeof item === "object" ? item.value : item));
}

export function canCreateRecord(query, options) {
	const text = (query || "").trim().toLowerCase();
	return Boolean(text) && !options.some((o) => String(o.value).toLowerCase() === text);
}

export function isMissing(value, options) {
	return Boolean(value) && options.length > 0 && !options.some((o) => o.value === value);
}
