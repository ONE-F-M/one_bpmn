import test from "node:test"
import assert from "node:assert/strict"
import { loadInstanceListState, saveInstanceListState } from "./instanceListState.js"

function fakeStorage(initial = {}) {
	const data = { ...initial }
	return {
		getItem: (k) => (k in data ? data[k] : null),
		setItem: (k, v) => {
			data[k] = v
		},
	}
}

test("saved filters are returned by the next load", () => {
	const storage = fakeStorage()
	const state = { filters: { process_model: "Leave", status: "Active" }, limitStart: 20 }
	saveInstanceListState(state, storage)
	assert.deepEqual(loadInstanceListState(storage), state)
})

test("nothing saved loads as an empty state", () => {
	assert.deepEqual(loadInstanceListState(fakeStorage()), {})
})

test("corrupt stored JSON loads as an empty state", () => {
	const storage = fakeStorage({ one_bpmn_instance_list_state: "{not json" })
	assert.deepEqual(loadInstanceListState(storage), {})
})

test("a storage that throws on write does not break the caller", () => {
	const storage = {
		setItem: () => {
			throw new Error("quota")
		},
	}
	assert.doesNotThrow(() => saveInstanceListState({ a: 1 }, storage))
})
