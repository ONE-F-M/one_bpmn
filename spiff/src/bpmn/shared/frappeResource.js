/**
 * frappeResource.js
 *
 * Shared REST helper for Frappe /api/resource/* and /api/method/* endpoints.
 * Uses native fetch (with credentials) to avoid response-format differences
 * between frappe.call (returns {message:…}) and the REST API ({data:[…]}).
 */

export function frappeGet(path, params = {}) {
	const qs = Object.entries(params)
		.filter(([, v]) => v !== undefined && v !== null)
		.map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(v)}`)
		.join("&");
	const url = qs ? `${path}?${qs}` : path;
	return fetch(url, { credentials: "include" })
		.then((r) => r.json())
		.then((json) => {
			if (json.data !== undefined) return json.data;
			if (json.message !== undefined) return json.message;
			return json;
		});
}
