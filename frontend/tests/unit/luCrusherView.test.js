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
