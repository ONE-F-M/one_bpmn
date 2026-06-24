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

/**
 * Resolve the Frappe CSRF token from the usual boot/cookie locations.
 */
export function getCsrfToken() {
	return (
		window.frappe?.csrf_token ||
		window.frappe?.boot?.csrf_token ||
		window.csrf_token ||
		document.cookie.split("; ").find((r) => r.startsWith("csrf_token="))?.split("=")[1] ||
		""
	);
}

/**
 * POST to a Frappe /api/method/* endpoint with the CSRF token attached.
 * Returns the unwrapped `message` payload (Frappe method response shape).
 */
export function frappePost(path, body = {}) {
	return fetch(path, {
		method: "POST",
		credentials: "include",
		headers: {
			"Content-Type": "application/json",
			"X-Frappe-CSRF-Token": getCsrfToken(),
		},
		body: JSON.stringify(body),
	})
		.then((r) => r.json())
		.then((json) => {
			if (json.message !== undefined) return json.message;
			if (json.data !== undefined) return json.data;
			return json;
		});
}
