/**
 * frappeResource.js
 *
 * Shared REST helper for Frappe /api/resource/* and /api/method/* endpoints.
 * Uses frappeRequest from frappe-ui for automatic CSRF handling,
 * credential inclusion, and consistent response unwrapping.
 */

import { frappeRequest } from "frappe-ui";

export function frappeGet(path, params = {}) {
	// frappe-ui 0.1.192's frappeRequest is unusable for /api/resource/* reads: it
	// defaults to POST (turning a read into a create — "… is required") and unwraps
	// the response to `data.message`, while /api/resource/* returns the payload under
	// `data.data`. Do a plain same-origin GET and read `.data` ourselves. Returns the
	// list array (or the doc object for a single-record path).
	const qs = new URLSearchParams(params).toString();
	return fetch(qs ? `${path}?${qs}` : path, {
		method: "GET",
		credentials: "same-origin",
		headers: { Accept: "application/json", "X-Frappe-CSRF-Token": getCsrfToken() },
	})
		.then((r) => r.json())
		.then((d) => (d && d.data !== undefined ? d.data : d && d.message !== undefined ? d.message : []));
}

/**
 * Resolve the Frappe CSRF token from the usual boot/cookie locations.
 * Retained for non-Vue contexts (bpmn-js Preact components) that may
 * still need it, although frappeRequest handles CSRF automatically.
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
 * POST to a Frappe /api/method/* endpoint.
 * Returns the unwrapped payload (frappeRequest handles the `message` key).
 */
export function frappePost(path, body = {}) {
	return frappeRequest({
		url: path,
		method: "POST",
		params: body,
	});
}
