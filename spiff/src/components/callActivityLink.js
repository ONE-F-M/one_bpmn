// A map-less process can only be linked from a non-executable caller, which is never deployed or run
export function isLinkable(model, callerExecutable) {
	return Boolean(model.active_process_id) || !callerExecutable
}
