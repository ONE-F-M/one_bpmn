// node --test spiff/src/utils/diagramAwareness.test.mjs

import { test } from "node:test"
import assert from "node:assert/strict"

import { AWARENESS_EVENT, PEER_TTL_MS, colorFor, createAwareness } from "./diagramAwareness.js"

function setup() {
	const sent = []
	let handler = null
	let peers = []
	let clock = 0
	const timers = { setInterval: (fn) => ((timers.beat = fn), 1), clearInterval() {}, setTimeout: (fn) => ((timers.pending = fn), 2), clearTimeout() {} }
	const awareness = createAwareness({
		request: async (url, params) => sent.push(params),
		realtime: { on: (_e, fn) => (handler = fn), off: () => (handler = null) },
		clientId: "me",
		hooks: { currentUser: () => "me@x", getState: () => ({ mode: "editing", selection: ["Task_1"] }), onPeers: (l) => (peers = l) },
		timers,
		now: () => clock,
	})
	return { awareness, sent, timers, peers: () => peers, tick: (ms) => (clock += ms), emit: (p) => handler({ model: "M", ...p }) }
}
const anna = (extra = {}) => ({ client_id: "a", user: "anna@x", full_name: "Anna", mode: "viewing", selection: ["T2"], ...extra })

test("colour is stable per user", () => {
	assert.equal(colorFor("anna@x"), colorFor("anna@x"))
	assert.notEqual(colorFor("anna@x"), colorFor("bob@x"))
})

test("joining announces our state; a peer shows with mode and selection; our own echo is ignored", () => {
	const t = setup()
	t.awareness.join("M")
	assert.deepEqual(t.sent[0], { model_name: "M", client_id: "me", mode: "editing", selection: ["Task_1"] })
	t.emit({ client_id: "me", user: "me@x", mode: "editing", selection: [] })
	assert.equal(t.peers().length, 0)
	t.emit(anna())
	assert.deepEqual(t.peers().map((p) => [p.fullName, p.mode, p.selection]), [["Anna", "viewing", ["T2"]]])
})

test("a newcomer gets one reply, and a reply is not answered (no echo loop)", () => {
	const t = setup()
	t.awareness.join("M")
	t.sent.length = 0
	t.emit(anna())
	assert.equal(t.sent.length, 1)
	assert.equal(t.sent[0].reply, 1)
	t.emit(anna({ reply: true, client_id: "b" }))
	t.emit(anna())
	assert.equal(t.sent.length, 1)
})

test("a peer that leaves or goes silent is removed", () => {
	const t = setup()
	t.awareness.join("M")
	t.emit(anna())
	t.emit(anna({ left: true }))
	assert.equal(t.peers().length, 0)
	t.emit(anna())
	t.tick(PEER_TTL_MS + 1)
	t.timers.beat()
	assert.equal(t.peers().length, 0)
})

test("events for another model are ignored; leaving tells the room", () => {
	const t = setup()
	t.awareness.join("M")
	t.emit(anna({ model: "Other" }))
	assert.equal(t.peers().length, 0)
	t.awareness.leave()
	assert.equal(t.sent.at(-1).left, 1)
})

test("announce is debounced into one send", () => {
	const t = setup()
	t.awareness.join("M")
	t.sent.length = 0
	t.awareness.announce()
	t.awareness.announce()
	t.timers.pending()
	assert.equal(t.sent.length, 1)
})
