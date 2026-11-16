import { ref, onUnmounted } from "vue"
import { frappeRequest } from "frappe-ui"
import { createAwareness, IDLE_AFTER_MS } from "@/utils/diagramAwareness"

const EDIT_WINDOW_MS = 30000

/**
 * Shows the other people with the open diagram. getSelection() returns the ids this user has selected,
 * canEdit() whether they may edit it. Call touchEdit() on every local change.
 */
export function useDiagramAwareness({ currentUser, getSelection, canEdit }) {
	const peers = ref([])
	let lastActive = Date.now()
	let lastEdit = 0

	function getState() {
		const selection = getSelection()
		if (Date.now() - lastActive > IDLE_AFTER_MS || document.hidden) return { mode: "idle", selection: [] }
		const editing = canEdit() && (selection.length > 0 || Date.now() - lastEdit < EDIT_WINDOW_MS)
		return { mode: editing ? "editing" : "viewing", selection }
	}

	const awareness = createAwareness({
		request: (url, params) => frappeRequest({ url, params }),
		realtime: window.frappe.realtime,
		clientId: crypto.randomUUID?.() || `${Date.now()}-${Math.random().toString(36).slice(2)}`,
		hooks: { currentUser, getState, onPeers: (list) => (peers.value = list) },
	})

	// Coming back from idle must be announced, not wait for the next heartbeat.
	const onActivity = () => {
		const wasIdle = Date.now() - lastActive > IDLE_AFTER_MS
		lastActive = Date.now()
		if (wasIdle) awareness.announce()
	}
	const events = ["pointerdown", "keydown", "wheel", "visibilitychange"]
	events.forEach((name) => window.addEventListener(name, onActivity, { passive: true }))
	onUnmounted(() => events.forEach((name) => window.removeEventListener(name, onActivity)))

	return {
		peers,
		join: awareness.join,
		leave: awareness.leave,
		announce: awareness.announce,
		touchEdit: () => {
			lastEdit = lastActive = Date.now()
			awareness.announce()
		},
	}
}
