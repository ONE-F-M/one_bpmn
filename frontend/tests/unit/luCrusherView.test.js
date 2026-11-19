import { test } from "vitest"
import assert from "node:assert/strict"

async function derive(shapes, hasShapes = true) {
	globalThis.window = {}
	const { deriveLuCrusherView } = await import("../../src/utils/luCrusherView.js")
	const proc = { name: "P1" }
	if (hasShapes) proc.shapes = shapes
	return deriveLuCrusherView({ intent: "TOPOLOGY_PROPOSAL", topology: { processes: [proc] } }).processes[0].shapes
}

test("a process with 8 shapes keeps all 8", async () => {
	const shapes = ["a", "b", "c", "d", "e", "f", "g", "h"]
	assert.deepEqual(await derive(shapes), shapes)
})

test("a comma-separated shapes string becomes whole names", async () => {
	assert.deepEqual(await derive("Start, Approve, End"), ["Start", "Approve", "End"])
})

test("newline-separated shapes are split and empty parts dropped", async () => {
	assert.deepEqual(await derive("Start\n\nApprove,, End\n"), ["Start", "Approve", "End"])
})

test("a missing shapes value becomes an empty array", async () => {
	assert.deepEqual(await derive(undefined, false), [])
})

test("a non-object process entry still gets an empty shapes array", async () => {
	globalThis.window = {}
	const { deriveLuCrusherView } = await import("../../src/utils/luCrusherView.js")
	const view = deriveLuCrusherView({ intent: "TOPOLOGY_PROPOSAL", topology: { processes: [null] } })
	assert.deepEqual(view.processes[0].shapes, [])
})

async function scanView(scan) {
	globalThis.window = {}
	const { deriveLuCrusherView } = await import("../../src/utils/luCrusherView.js")
	return deriveLuCrusherView({ intent: "CODEBASE_SCAN_RESULT", codebase_scan: scan })
}

test("each matched DocType carries the words and score behind it", async () => {
	const view = await scanView({
		matched_doctypes: [{ doctype: "Leave Application", reason: "words application, leave · score 1.0" }],
		counts: { doctypes: 1 },
	})
	assert.deepEqual(view.doctypes, [{ name: "Leave Application", note: "words application, leave · score 1.0" }])
})

test("the count is how many matched, not how many arrived", async () => {
	const view = await scanView({
		matched_doctypes: [{ doctype: "A" }, { doctype: "B" }],
		counts: { doctypes: 75 },
	})
	assert.equal(view.doctypes.length, 2)
	assert.equal(view.doctypeTotal, 75)
})

test("a scan with no match carries the reason, not a bare zero", async () => {
	const view = await scanView({ matched_doctypes: [], counts: { doctypes: 0 }, no_match_reason: "0 DocTypes matched: check the step names." })
	assert.equal(view.noMatchReason, "0 DocTypes matched: check the step names.")
	assert.equal((await scanView({ matched_doctypes: [{ doctype: "A" }], no_match_reason: "stale" })).noMatchReason, "")
})
