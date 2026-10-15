// Copyright (c) 2026, one-fm and contributors
// The progress line for a long drawing (WI-003582).
//
// Contract with the backend: a CUSTOM event named `onefm.progress` whose value
// is { phase: int, total: int, message: string }. The backend does not emit it
// yet, so this reads it defensively: anything that is not that shape yields ""
// and the panel simply shows no progress line.

const MAX_LINE_LENGTH = 300;

/**
 * The text to show for a `onefm.progress` value, or "" when there is nothing
 * usable. The message wins; without one, phase and total build the line.
 *
 * @param {*} value  the event's value, of any shape
 * @param {(text: string) => string} [translate]  the panel's `__`
 */
export function progressLineFor(value, translate = (text) => text) {
	if (!value || typeof value !== "object") return "";
	const message = typeof value.message === "string" ? value.message.trim() : "";
	if (message) return message.slice(0, MAX_LINE_LENGTH);
	const { phase, total } = value;
	if (Number.isInteger(phase) && Number.isInteger(total) && phase > 0 && total >= phase) {
		return translate("Drawing part {0} of {1}").replace("{0}", phase).replace("{1}", total);
	}
	return "";
}
