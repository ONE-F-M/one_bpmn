const KEY = "one_bpmn_instance_list_state"

export function loadInstanceListState(storage = window.sessionStorage) {
	try {
		const parsed = JSON.parse(storage.getItem(KEY))
		return parsed && typeof parsed === "object" ? parsed : {}
	} catch {
		return {}
	}
}

export function saveInstanceListState(state, storage = window.sessionStorage) {
	try {
		storage.setItem(KEY, JSON.stringify(state))
	} catch {
		// Storage is unavailable (private mode or quota); filters just are not retained.
	}
}
