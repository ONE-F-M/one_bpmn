// Who else has this diagram open, whether they edit or only view, and which elements they have selected.
// Ephemeral: relayed over frappe.realtime by processa.api.collaboration.set_awareness, never saved.

const API = "processa.api.collaboration.set_awareness"

export const AWARENESS_EVENT = "bpmn_diagram_awareness"
export const ANNOUNCE_DEBOUNCE_MS = 100
export const HEARTBEAT_MS = 10000
// A peer that has not announced for this long (closed tab, lost network) is dropped.
export const PEER_TTL_MS = 25000
export const IDLE_AFTER_MS = 60000

// The same user always gets the same colour, on every screen.
export function colorFor(user) {
	let hash = 0
	for (const char of user) hash = (hash * 31 + char.charCodeAt(0)) >>> 0
	return `hsl(${hash % 360} 70% 45%)`
}

/**
 * hooks: currentUser(), getState() -> { mode: "editing" | "viewing" | "idle", selection: [id] },
 * onPeers(list) with [{ clientId, user, fullName, mode, selection, color }].
 * realtime: { on, off }. now() is injectable for tests.
 */
export function createAwareness({ request, realtime, clientId, hooks, timers = globalThis, now = Date.now }) {
	let model = null
	let beat = null
	let announceTimer = null
	const peers = new Map()

	const publish = () => hooks.onPeers([...peers.values()].sort((a, b) => a.fullName.localeCompare(b.fullName)))

	function send(extra = {}) {
		if (model === null) return
		const { mode, selection } = hooks.getState()
		request(API, { model_name: model, client_id: clientId, mode, selection, ...extra }).catch(() => {})
	}

	function prune() {
		let changed = false
		for (const [id, peer] of peers) {
			if (now() - peer.seenAt > PEER_TTL_MS) {
				peers.delete(id)
				changed = true
			}
		}
		if (changed) publish()
	}

	function onEvent(payload) {
		if (payload.model !== model || payload.client_id === clientId) return
		const isNew = !peers.has(payload.client_id)
		if (payload.left) {
			if (peers.delete(payload.client_id)) publish()
			return
		}
		peers.set(payload.client_id, {
			clientId: payload.client_id,
			user: payload.user,
			fullName: payload.full_name || payload.user,
			mode: payload.mode,
			selection: payload.selection || [],
			color: colorFor(payload.user),
			seenAt: now(),
		})
		publish()
		// Tell a newcomer about ourselves once; replies are never answered, so no echo loop.
		if (isNew && !payload.reply) send({ reply: 1 })
	}

	function join(name) {
		leave()
		model = name
		realtime.on(AWARENESS_EVENT, onEvent)
		send()
		beat = timers.setInterval(() => {
			prune()
			send()
		}, HEARTBEAT_MS)
	}

	function leave() {
		if (model === null) return
		send({ left: 1 })
		timers.clearInterval(beat)
		timers.clearTimeout(announceTimer)
		realtime.off(AWARENESS_EVENT, onEvent)
		model = null
		peers.clear()
		publish()
	}

	// Call whenever the selection, the edit state or the idle state may have changed.
	function announce() {
		if (model === null) return
		timers.clearTimeout(announceTimer)
		announceTimer = timers.setTimeout(send, ANNOUNCE_DEBOUNCE_MS)
	}

	return { join, leave, announce }
}
