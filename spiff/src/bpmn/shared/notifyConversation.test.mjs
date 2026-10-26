import { test } from "node:test"
import assert from "node:assert/strict"

import { missingConversationAction, parseConversation } from "./notifyConversation.js"

test("parseConversation: nothing saved offers Reply and Add Note, no notes, no saved replies", () => {
	assert.deepEqual(parseConversation(""), {
		actions: [{ key: "reply", completesWith: "" }, { key: "note", completesWith: "" }],
		internalNotes: false,
		canned: [],
	})
})

test("parseConversation: keeps saved settings and drops unknown actions", () => {
	const raw = JSON.stringify({ actions: [{ key: "note", completesWith: "Resolve" }, { key: "resolve" }], internalNotes: true, canned: ["Acknowledge"] })
	assert.deepEqual(parseConversation(raw), { actions: [{ key: "note", completesWith: "Resolve" }], internalNotes: true, canned: ["Acknowledge"] })
})

test("parseConversation: an old completes tick reads as do not finish", () => {
	assert.deepEqual(parseConversation(JSON.stringify({ actions: [{ key: "reply", completes: true }] })).actions, [{ key: "reply", completesWith: "" }])
})

test("parseConversation: an emptied action list stays empty", () => {
	assert.deepEqual(parseConversation(JSON.stringify({ actions: [] })).actions, [])
})

test("missingConversationAction: names the action that can be added back", () => {
	assert.equal(missingConversationAction([{ key: "note" }]), "reply")
	assert.equal(missingConversationAction([]), "reply")
	assert.equal(missingConversationAction([{ key: "reply" }, { key: "note" }]), undefined)
})
