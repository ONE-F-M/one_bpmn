import { test } from "node:test"
import assert from "node:assert/strict"

import { missingConversationAction, parseConversation } from "./notifyConversation.js"

test("parseConversation: nothing saved offers Reply and Add Note, no notes, no saved replies", () => {
	assert.deepEqual(parseConversation(""), {
		actions: [{ key: "reply", label: "Reply" }, { key: "note", label: "Add Note" }],
		internalNotes: false,
		canned: [],
	})
})

test("parseConversation: keeps saved settings and custom labels, drops unknown actions", () => {
	const raw = JSON.stringify({ actions: [{ key: "note", label: "Log a remark" }, { key: "resolve" }], internalNotes: true, canned: ["Acknowledge"] })
	assert.deepEqual(parseConversation(raw), { actions: [{ key: "note", label: "Log a remark" }], internalNotes: true, canned: ["Acknowledge"] })
})

test("parseConversation: an empty label falls back to the default", () => {
	assert.deepEqual(parseConversation(JSON.stringify({ actions: [{ key: "reply", label: "  " }] })).actions, [{ key: "reply", label: "Reply" }])
})

test("parseConversation: an old finish setting is dropped", () => {
	assert.deepEqual(parseConversation(JSON.stringify({ actions: [{ key: "reply", completesWith: "Resolve" }] })).actions, [{ key: "reply", label: "Reply" }])
})

test("parseConversation: an emptied action list stays empty", () => {
	assert.deepEqual(parseConversation(JSON.stringify({ actions: [] })).actions, [])
})

test("missingConversationAction: names the action that can be added back", () => {
	assert.equal(missingConversationAction([{ key: "note" }]), "reply")
	assert.equal(missingConversationAction([]), "reply")
	assert.equal(missingConversationAction([{ key: "reply" }, { key: "note" }]), undefined)
})
