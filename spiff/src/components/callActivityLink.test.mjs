import test from "node:test"
import assert from "node:assert/strict"
import { isLinkable } from "./callActivityLink.js"

test("a non-executable caller can link a process with no active map", () => {
	assert.equal(isLinkable({ name: "Daily", active_process_id: null }, false), true)
})

test("an executable caller cannot link a process with no active map", () => {
	assert.equal(isLinkable({ name: "Daily", active_process_id: null }, true), false)
})

test("a process with an active map is linkable from any caller", () => {
	assert.equal(isLinkable({ name: "Daily", active_process_id: "Process_1" }, true), true)
	assert.equal(isLinkable({ name: "Daily", active_process_id: "Process_1" }, false), true)
})
