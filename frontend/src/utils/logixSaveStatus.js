// Why the Logix canvas is not auto-saving, as one line for the status area.
// Pure: LogixCanvas feeds it the live read-only flag, the script name and the last request error.

const NAME_REQUIRED_MESSAGE = "Name the script to save it";
const READONLY_MESSAGE = "Read-only map: changes are not saved";

export function saveStatusLabel({ readonly = false, name = "", error = "" } = {}) {
	if (readonly) return READONLY_MESSAGE;
	if (!String(name ?? "").trim()) return NAME_REQUIRED_MESSAGE;
	return error ? String(error) : "";
}
