export function deskUrl(doctype, name) {
	const slug = String(doctype || "")
		.toLowerCase()
		.replace(/ /g, "-");
	return `/app/${slug}/${encodeURIComponent(name)}`;
}
