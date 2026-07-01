/**
 * frappeResource.js
 *
 * Shared REST helper for Frappe /api/resource/* and /api/method/* endpoints.
 * Uses frappeRequest from frappe-ui for automatic CSRF handling,
 * credential inclusion, and consistent response unwrapping.
 */

import { frappeRequest } from "frappe-ui";

export function frappeGet(path, params = {}) {
	return frappeRequest({
		url: path,
		params,
	});
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
