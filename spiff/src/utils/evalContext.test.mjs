import { test } from "node:test"
import assert from "node:assert/strict"

import { earlierTurns, mergeContexts, midConversationError, savedState } from "./evalContext.js"

test("midConversationError: an empty box asks for the conversation", () => {
	assert.match(midConversationError(""), /untick Include earlier conversation/)
})

test("midConversationError: text that is not JSON is refused", () => {
	assert.equal(midConversationError("{nope"), "The earlier conversation is not valid JSON.")
})

test("midConversationError: a message without a known type is named", () => {
	const text = JSON.stringify({ conversation_messages: [{ message_type: "User", text: "hi" }, { text: "no type" }] })
	assert.equal(midConversationError(text), "Message 2 needs a message_type of User, Bot or Tool.")
})

test("midConversationError: a valid conversation passes", () => {
	const text = JSON.stringify({ conversation_messages: [{ message_type: "Bot", text: "hello" }], session_state: {} })
	assert.equal(midConversationError(text), "")
})

test("earlierTurns: keeps User and Bot turns in order, drops Tool rows", () => {
	const context = {
		conversation_messages: [
			{ message_type: "User", text: "a" },
			{ message_type: "Tool", text: "__state__", metadata: { intent: "X" } },
			{ message_type: "Bot", text: "b" },
		],
	}
	assert.deepEqual(earlierTurns(context), [{ role: "User", text: "a" }, { role: "Bot", text: "b" }])
})

test("savedState: carries Tool metadata and session_state, or null when there is none", () => {
	const context = {
		conversation_messages: [{ message_type: "Tool", text: "__state__", metadata: '{"intent": "X"}' }],
		session_state: { "lucid_doc:1": { title: "Visa" } },
	}
	assert.deepEqual(savedState(context), {
		migration_context: [{ intent: "X" }],
		session_state: { "lucid_doc:1": { title: "Visa" } },
	})
	assert.equal(savedState({ conversation_messages: [{ message_type: "User", text: "a" }] }), null)
})

test("mergeContexts: turns from each conversation in order, latest snapshot last, state merged", () => {
	const first = {
		conversation_messages: [
			{ message_type: "User", text: "a" },
			{ message_type: "Tool", text: "__state__", metadata: { intent: "ONE" } },
			{ message_type: "Bot", text: "b" },
		],
		session_state: { k1: 1, shared: "old" },
	}
	const second = {
		conversation_messages: [{ message_type: "User", text: "c" }, { message_type: "Tool", text: "__state__", metadata: { intent: "TWO" } }],
		session_state: { shared: "new" },
	}
	assert.deepEqual(mergeContexts([first, null, second]), {
		conversation_messages: [
			{ message_type: "User", text: "a" },
			{ message_type: "Bot", text: "b" },
			{ message_type: "User", text: "c" },
			{ message_type: "Tool", text: "__state__", metadata: { intent: "TWO" } },
		],
		session_state: { k1: 1, shared: "new" },
	})
})
