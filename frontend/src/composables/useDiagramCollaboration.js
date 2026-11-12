import { ref } from "vue"
import { frappeRequest } from "frappe-ui"
import { createDiagramCollaboration } from "@/utils/diagramCollaboration"
import { useCurrentUser } from "@/composables/useCurrentUser"

function newClientId() {
	return crypto.randomUUID?.() || `${Date.now()}-${Math.random().toString(36).slice(2)}`
}

// The SPA polyfills on/off/emit; the Desk's own realtime has doc_subscribe and doc_unsubscribe.
function frappeRealtime() {
	const realtime = window.frappe.realtime
	const room = (event, doctype, name) =>
		realtime[event] ? realtime[event](doctype, name) : realtime.emit(event, doctype, name)
	return {
		on: (event, fn) => realtime.on(event, fn),
		off: (event, fn) => realtime.off(event, fn),
		subscribe: (doctype, name) => room("doc_subscribe", doctype, name),
		unsubscribe: (doctype, name) => room("doc_unsubscribe", doctype, name),
	}
}

/**
 * Shares one open diagram with the other editors of the same model.
 * hasLocalChanges() and applyXml(xml) tie it to the editor; getLiveXml() reads the canvas without disturbing it.
 */
export function useDiagramCollaboration({ hasLocalChanges, applyXml, getLiveXml, onEditors }) {
	const { currentUser } = useCurrentUser()
	const conflict = ref(null)
	const status = ref("idle")
	const statusMessage = ref("")

	const collaboration = createDiagramCollaboration({
		request: (url, params) => frappeRequest({ url, params }),
		realtime: frappeRealtime(),
		clientId: newClientId(),
		hooks: {
			currentUser: () => currentUser.value,
			hasLocalChanges,
			applyXml,
			onEditors,
			onConflict: (next) => {
				conflict.value = next
			},
			onStatus: (next, error) => {
				status.value = next
				statusMessage.value = error?.message || ""
			},
		},
	})

	return {
		conflict,
		status,
		statusMessage,
		join: collaboration.join,
		leave: collaboration.leave,
		synced: collaboration.synced,
		save: collaboration.save,
		loadLatest: collaboration.loadLatest,
		keepMine: collaboration.keepMine,
		publishLive: () => collaboration.scheduleLive(getLiveXml),
	}
}
