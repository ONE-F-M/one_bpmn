// node --test spiff/src/utils/diagramCollaboration.test.mjs

import { test } from "node:test"
import assert from "node:assert/strict"

import {
	EVENTS,
	HEARTBEAT_MS,
	LIVE_DEBOUNCE_MS,
	MAX_LIVE_XML_CHARS,
	createDiagramCollaboration,
} from "./diagramCollaboration.js"

const MODEL = "Onboarding"
const ME = "me@example.com"
const ANNA = { name: "anna@example.com", full_name: "Anna", user_image: null }
const settle = () => new Promise((resolve) => setImmediate(resolve))

function setup({ server = {}, local = false } = {}) {
	const state = { revision: 3, xml: "<v3/>", editors: [{ name: ME }, ANNA], modified_by: "Anna", ...server }
	const calls = []
	const handlers = {}
	const timers = { intervals: [], timeouts: [] }
	const seen = { xml: [], editors: null, conflict: null, statuses: [], local }

	const methods = {
		join_model: () => ({ revision: state.revision, editors: state.editors }),
		leave_model: () => ({}),
		get_model_state: () => ({ revision: state.revision, bpmn_xml: state.xml, modified_by: state.modified_by }),
		save_diagram: (params) => {
			state.revision += 1
			state.xml = params.xml_content
			return { saved: true, revision: state.revision }
		},
		publish_diagram_change: () => ({ ok: true, stale: false, revision: state.revision }),
	}
	const request = async (url, params) => {
		const method = url.split(".").pop()
		calls.push({ method, params })
		return methods[method](params)
	}
	const realtime = {
		on: (event, fn) => (handlers[event] = fn),
		off: (event) => delete handlers[event],
		subscribe: (...args) => calls.push({ method: "subscribe", params: args }),
		unsubscribe: (...args) => calls.push({ method: "unsubscribe", params: args }),
	}
	const fakeTimers = {
		setInterval: (fn, ms) => (timers.intervals.push({ fn, ms }), timers.intervals.length),
		clearInterval: () => {},
		setTimeout: (fn, ms) => (timers.timeouts.push({ fn, ms }), timers.timeouts.length),
		clearTimeout: () => {},
	}
	const hooks = {
		currentUser: () => ME,
		hasLocalChanges: () => seen.local,
		applyXml: async (xml) => seen.xml.push(xml),
		onEditors: (list) => (seen.editors = list),
		onConflict: (conflict) => (seen.conflict = conflict),
		onStatus: (status, error) => seen.statuses.push([status, error?.message]),
	}
	const collab = createDiagramCollaboration({ request, realtime, clientId: "tab-1", hooks, timers: fakeTimers })
	return { collab, state, methods, calls, handlers, timers, seen }
}

const called = (calls, method) => calls.filter((c) => c.method === method)

test("joining subscribes to the model room and lists the other editors", async () => {
	const { collab, calls, seen } = setup()
	await collab.join(MODEL)
	assert.deepEqual(called(calls, "subscribe")[0].params, ["BPMN Process Model", MODEL])
	assert.deepEqual(seen.editors, [ANNA])
})

test("another user's save is pulled in when this client has no edits of its own", async () => {
	const { collab, state, handlers, seen } = setup()
	await collab.join(MODEL)
	await collab.synced("<v3/>")
	state.revision = 4
	state.xml = "<v4/>"
	handlers[EVENTS.saved]({ model: MODEL, revision: 4, client_id: "tab-2" })
	await settle()
	assert.deepEqual(seen.xml, ["<v4/>"])
})

test("this client's own save event is ignored", async () => {
	const { collab, calls, handlers } = setup()
	await collab.join(MODEL)
	handlers[EVENTS.saved]({ model: MODEL, revision: 4, client_id: "tab-1" })
	await settle()
	assert.equal(called(calls, "get_model_state").length, 0)
})

test("a live change from another tab is applied only when this client has no edits", async () => {
	const { collab, handlers, seen } = setup()
	await collab.join(MODEL)
	const event = { model: MODEL, revision: 3, client_id: "tab-2", change: { type: "xml", xml: "<live/>" } }
	handlers[EVENTS.change](event)
	await settle()
	assert.deepEqual(seen.xml, ["<live/>"])

	seen.local = true
	handlers[EVENTS.change]({ ...event, change: { type: "xml", xml: "<later/>" } })
	handlers[EVENTS.change]({ ...event, client_id: "tab-1", change: { type: "xml", xml: "<mine/>" } })
	await settle()
	assert.deepEqual(seen.xml, ["<live/>"])
})

test("a save by someone else while this client has edits is flagged, not applied", async () => {
	const { collab, state, handlers, seen } = setup()
	await collab.join(MODEL)
	await collab.synced("<v3/>")
	seen.local = true
	state.revision = 4
	state.xml = "<v4/>"
	handlers[EVENTS.saved]({ model: MODEL, revision: 4, client_id: "tab-2" })
	await settle()
	assert.deepEqual(seen.xml, [])
	assert.match(seen.conflict.message, /Anna changed this diagram/)
})

test("loading the latest version resolves a conflict by taking the server's diagram", async () => {
	const { collab, state, handlers, seen } = setup()
	await collab.join(MODEL)
	await collab.synced("<v3/>")
	seen.local = true
	state.revision = 4
	state.xml = "<v4/>"
	handlers[EVENTS.saved]({ model: MODEL, revision: 4, client_id: "tab-2" })
	await settle()
	await collab.loadLatest()
	assert.deepEqual(seen.xml, ["<v4/>"])
	assert.equal(seen.conflict, null)
})

test("keeping my edits rebases the next save onto the server's revision", async () => {
	const { collab, state, calls, handlers, seen } = setup()
	await collab.join(MODEL)
	await collab.synced("<v3/>")
	seen.local = true
	state.revision = 5
	state.xml = "<v5/>"
	handlers[EVENTS.saved]({ model: MODEL, revision: 5, client_id: "tab-2" })
	await settle()
	await collab.keepMine()
	await collab.save("<mine/>", "d")
	assert.equal(called(calls, "save_diagram")[0].params.base_revision, 5)
	assert.equal(seen.conflict, null)
})

test("a save is based on the revision this client loaded and moves it forward", async () => {
	const { collab, calls } = setup()
	await collab.join(MODEL)
	assert.deepEqual(await collab.save("<a/>", "desc"), { saved: true })
	await collab.save("<b/>", "desc")
	const [first, second] = called(calls, "save_diagram")
	assert.equal(first.params.base_revision, 3)
	assert.equal(first.params.client_id, "tab-1")
	assert.equal(second.params.base_revision, 4)
})

test("a stale save reports a conflict and loses nothing", async () => {
	const { collab, methods, seen } = setup()
	await collab.join(MODEL)
	methods.save_diagram = () => {
		throw Object.assign(new Error("x"), { exc_type: "StaleDiagramRevision", messages: ["Anna changed this."] })
	}
	assert.deepEqual(await collab.save("<mine/>", ""), { saved: false })
	assert.equal(seen.conflict.message, "Anna changed this.")
})

test("an error that is not a stale save is raised to the caller", async () => {
	const { collab, methods } = setup()
	await collab.join(MODEL)
	methods.save_diagram = () => {
		throw new Error("boom")
	}
	await assert.rejects(collab.save("<x/>", ""), /boom/)
})

test("a diagram loaded from a stale cache is replaced by the server's copy", async () => {
	const { collab, seen } = setup()
	await collab.join(MODEL)
	await collab.synced("<old-cache/>")
	assert.deepEqual(seen.xml, ["<v3/>"])
})

test("a diagram already level with the server is not reloaded", async () => {
	const { collab, seen } = setup()
	await collab.join(MODEL)
	await collab.synced("<v3/>")
	assert.deepEqual(seen.xml, [])
})

test("edits are published once after a pause, based on the current revision", async () => {
	const { collab, calls, timers } = setup()
	await collab.join(MODEL)
	collab.scheduleLive(async () => "<one/>")
	collab.scheduleLive(async () => "<two/>")
	assert.equal(timers.timeouts.at(-1).ms, LIVE_DEBOUNCE_MS)
	await timers.timeouts.at(-1).fn()
	const [publish] = called(calls, "publish_diagram_change")
	assert.deepEqual(publish.params.change, { type: "xml", xml: "<two/>" })
	assert.equal(publish.params.base_revision, 3)
})

test("a publish that is stale triggers a re-sync", async () => {
	const { collab, calls, methods, timers } = setup()
	await collab.join(MODEL)
	methods.publish_diagram_change = () => ({ ok: false, stale: true, current_revision: 4 })
	collab.scheduleLive(async () => "<x/>")
	await timers.timeouts.at(-1).fn()
	await settle()
	assert.equal(called(calls, "get_model_state").length, 1)
})

test("a diagram too large for a live change is reported as paused and not sent", async () => {
	const { collab, calls, timers, seen } = setup()
	await collab.join(MODEL)
	collab.scheduleLive(async () => "x".repeat(MAX_LIVE_XML_CHARS + 1))
	await timers.timeouts.at(-1).fn()
	assert.equal(called(calls, "publish_diagram_change").length, 0)
	assert.equal(seen.statuses.at(-1)[0], "paused")
})

test("the heartbeat recovers a save whose event never arrived", async () => {
	const { collab, state, timers, seen } = setup()
	await collab.join(MODEL)
	await collab.synced("<v3/>")
	state.revision = 4
	state.xml = "<v4/>"
	assert.equal(timers.intervals[0].ms, HEARTBEAT_MS)
	await timers.intervals[0].fn()
	await settle()
	assert.deepEqual(seen.xml, ["<v4/>"])
})

test("leaving unsubscribes, stops listening and tells the server", async () => {
	const { collab, calls, handlers } = setup()
	await collab.join(MODEL)
	await collab.leave()
	assert.equal(called(calls, "unsubscribe").length, 1)
	assert.equal(called(calls, "leave_model").length, 1)
	assert.deepEqual(Object.keys(handlers), [])
})
