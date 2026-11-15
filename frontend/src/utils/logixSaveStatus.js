// Why the Logix canvas is not auto-saving, as one line for the status area.
// Pure: no Vue, no requests — LogixCanvas feeds it the live read-only flag,
// the script name and the last request error.

export const NAME_REQUIRED_MESSAGE = "Name the script to save it";
export const READONLY_MESSAGE = "Read-only map: changes are not saved";

/**
 * Pick the label to show, or "" when nothing is wrong.
 * Order: read-only, then missing name, then a failed request. The first two are
 * derived from live state, so a stale copy of them held as `error` is ignored
 * once the map is unlocked or the script has been named.
 */
export function saveStatusLabel({ readonly = false, name = "", error = "" } = {}) {
	if (readonly) return READONLY_MESSAGE;
	if (!String(name ?? "").trim()) return NAME_REQUIRED_MESSAGE;
	if (error === NAME_REQUIRED_MESSAGE || error === READONLY_MESSAGE) return "";
	return error ? String(error) : "";
}
