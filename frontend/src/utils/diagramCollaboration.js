// Client side of processa.api.collaboration: presence, live diagram sync, revision-checked saves.

const DOCTYPE = "BPMN Process Model"
const API = "processa.api.collaboration"

export const EVENTS = {
	change: "bpmn_diagram_change",
	saved: "bpmn_diagram_saved",
	presence: "bpmn_editor_presence",
}
export const HEARTBEAT_MS = 25000
export const LIVE_DEBOUNCE_MS = 300
// The server refuses a live change over 256 KB, JSON wrapper included.
export const MAX_LIVE_XML_CHARS = 200000

export function isStaleSave(error) {
	return error?.exc_type === "StaleDiagramRevision" || error?.response?.status === 409
}

/**
 * hooks: currentUser(), hasLocalChanges(), applyXml(xml), onEditors(list), onConflict(conflict|null),
 * onStatus("live" | "paused" | "error", error?). realtime: { on, off, subscribe, unsubscribe }.
 */
export function createDiagramCollaboration({ request, realtime, clientId, hooks, timers = globalThis }) {
	let model = null
	let revision = null
	let lastXml = null
	let conflict = null
	let joined = null
	let heartbeat = null
	let liveTimer = null
	let saveInFlight = false
	let queue = Promise.resolve()

	const call = (method, params) => request(`${API}.${method}`, params)
	const identity = (name) => ({ model_name: name, client_id: clientId })
	const isCurrent = (name) => model === name
	const others = (editors) => editors.filter((editor) => editor.name !== hooks.currentUser())

	function setConflict(next) {
		conflict = next
		hooks.onConflict(next)
	}

	function enqueue(task) {
		queue = queue.then(task).catch((error) => hooks.onStatus("error", error))
		return queue
	}

	// Brings this client level with the server unless a save of its own is in flight.
	async function sync() {
		if (saveInFlight) return
		const name = model
		const state = await call("get_model_state", { model_name: name })
		if (!isCurrent(name)) return
		if (state.bpmn_xml === lastXml) {
			revision = state.revision
			setConflict(null)
			return
		}
		if (hooks.hasLocalChanges()) {
			setConflict({ message: `${state.modified_by} changed this diagram while you were editing it.` })
			return
		}
		await hooks.applyXml(state.bpmn_xml)
		lastXml = state.bpmn_xml
		revision = state.revision
		setConflict(null)
	}

	function onPresence(payload) {
		if (!isCurrent(payload.model)) return
		hooks.onEditors(others(payload.editors))
	}

	function onSaved(payload) {
		if (!isCurrent(payload.model) || payload.client_id === clientId) return
		if (revision !== null && payload.revision <= revision) return
		enqueue(sync)
	}

	function onChange(payload) {
		if (!isCurrent(payload.model) || payload.client_id === clientId) return
		if (payload.change?.type !== "xml") return
		enqueue(async () => {
			if (hooks.hasLocalChanges()) return
			await hooks.applyXml(payload.change.xml)
			lastXml = payload.change.xml
			revision = payload.revision
		})
	}

	async function beat() {
		const name = model
		const state = await call("join_model", identity(name))
		if (!isCurrent(name)) return
		hooks.onEditors(others(state.editors))
		if (state.revision !== revision) enqueue(sync)
	}

	function bind() {
		realtime.on(EVENTS.presence, onPresence)
		realtime.on(EVENTS.saved, onSaved)
		realtime.on(EVENTS.change, onChange)
	}

	function unbind() {
		realtime.off(EVENTS.presence, onPresence)
		realtime.off(EVENTS.saved, onSaved)
		realtime.off(EVENTS.change, onChange)
	}

	function join(name) {
		if (isCurrent(name)) return joined
		leave()
		model = name
		revision = null
		lastXml = null
		bind()
		realtime.subscribe(DOCTYPE, name)
		joined = call("join_model", identity(name)).then((state) => {
			if (!isCurrent(name)) return
			revision = state.revision
			hooks.onEditors(others(state.editors))
			heartbeat = timers.setInterval(
				() => beat().catch((error) => hooks.onStatus("error", error)),
				HEARTBEAT_MS,
			)
		})
		return joined
	}

	async function leave() {
		if (model === null) return
		const name = model
		model = null
		joined = null
		timers.clearInterval(heartbeat)
		timers.clearTimeout(liveTimer)
		heartbeat = null
		liveTimer = null
		unbind()
		realtime.unsubscribe(DOCTYPE, name)
		hooks.onEditors([])
		setConflict(null)
		try {
			await call("leave_model", identity(name))
		} catch (error) {
			hooks.onStatus("error", error)
		}
	}

	// Records the XML the editor just loaded, then reconciles it with the server's copy.
	async function synced(xml) {
		lastXml = xml
		if (!joined) return
		await joined
		return enqueue(sync)
	}

	async function save(xml, description) {
		await joined
		if (revision === null) throw new Error("Not connected to the shared diagram")
		saveInFlight = true
		try {
			const result = await call("save_diagram", {
				...identity(model),
				xml_content: xml,
				base_revision: revision,
				description,
			})
			revision = result.revision
			lastXml = xml
			setConflict(null)
			return { saved: true }
		} catch (error) {
			if (!isStaleSave(error)) throw error
			setConflict({ message: error.messages?.[0] || "Someone else changed this diagram." })
			return { saved: false }
		} finally {
			saveInFlight = false
		}
	}

	async function publishLive(getXml) {
		const name = model
		const xml = await getXml()
		if (!xml || !isCurrent(name) || conflict || revision === null) return
		if (xml.length > MAX_LIVE_XML_CHARS) {
			hooks.onStatus("paused", new Error("This diagram is too large for live sync. Changes are still saved."))
			return
		}
		const result = await call("publish_diagram_change", {
			...identity(name),
			base_revision: revision,
			change: { type: "xml", xml },
		})
		if (result.stale) {
			enqueue(sync)
			return
		}
		hooks.onStatus("live")
	}

	function scheduleLive(getXml) {
		if (model === null || conflict) return
		timers.clearTimeout(liveTimer)
		liveTimer = timers.setTimeout(
			() => publishLive(getXml).catch((error) => hooks.onStatus("paused", error)),
			LIVE_DEBOUNCE_MS,
		)
	}

	// Discards this client's edits and takes the server's diagram.
	async function loadLatest() {
		const state = await call("get_model_state", { model_name: model })
		await hooks.applyXml(state.bpmn_xml)
		lastXml = state.bpmn_xml
		revision = state.revision
		setConflict(null)
	}

	// Keeps this client's edits: the next save is based on the server's current revision.
	async function keepMine() {
		const state = await call("get_model_state", { model_name: model })
		revision = state.revision
		setConflict(null)
	}

	return { join, leave, synced, save, scheduleLive, loadLatest, keepMine }
}
