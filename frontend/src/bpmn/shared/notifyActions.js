/**
 * notifyActions holds the email-only settings per Task Action, keyed by action
 * name: { primary, reason, reasonField, chips: [[en, ar]] }. notifyTokenHours
 * holds the button life, empty when it is the 72-hour default.
 */
export const DEFAULT_TOKEN_HOURS = 72;
export const MAX_TOKEN_HOURS = 720;

/** Settings for the current Task Actions only, in their order, with exactly one primary. */
export function mergeNotifyActions(taskActions, raw) {
	let saved = {};
	if (raw) saved = JSON.parse(raw);
	const merged = {};
	for (const { action, requireDigitalSignature } of taskActions || []) {
		if (!action) continue;
		const prev = saved[action] || {};
		const sign = requireDigitalSignature === "true";
		merged[action] = {
			primary: !!prev.primary,
			reason: !sign && !!prev.reason,
			reasonField: prev.reasonField || "",
			chips: Array.isArray(prev.chips) ? prev.chips : [],
		};
	}
	const names = Object.keys(merged);
	if (names.length && !names.some((n) => merged[n].primary)) merged[names[0]].primary = true;
	return merged;
}

export function serializeNotifyActions(actions) {
	return Object.keys(actions).length ? JSON.stringify(actions) : "";
}

/** The hours the email buttons stay usable: 1 to 720, 72 when not a number. */
export function clampTokenHours(value) {
	const hours = Number.parseInt(value, 10);
	if (Number.isNaN(hours)) return DEFAULT_TOKEN_HOURS;
	return Math.min(MAX_TOKEN_HOURS, Math.max(1, hours));
}

export function serializeTokenHours(hours) {
	return hours === DEFAULT_TOKEN_HOURS ? "" : String(hours);
}
