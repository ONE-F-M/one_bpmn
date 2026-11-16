import { test } from "vitest"
import assert from "node:assert/strict"

import { toolBoxOptions } from "../../src/bpmn/shared/toolBoxOptions.js"

const translate = (text) => text
const shape = ($type, id, name, attrs = {}) => ({ $type, id, name, get: (key) => attrs[key] })

const DIAGRAM = [
	shape("bpmn:ServiceTask", "Agent_1", "Triage"),
	shape("bpmn:AdHocSubProcess", "Tools_A", "Lookup tools"),
	shape("bpmn:AdHocSubProcess", "Tools_B", ""),
	shape("bpmn:AdHocSubProcess", "Tools_A", "Lookup tools"),
	shape("bpmn:AdHocSubProcess", "Selector_1", "Pick a task", { "spiffworkflow:serviceType": "ai_task_selector" }),
]

test("every tools box in the diagram is listed once by name and id", () => {
	assert.deepEqual(toolBoxOptions(DIAGRAM, "", translate), [
		{ value: "", label: "No tools" },
		{ value: "Tools_A", label: "Lookup tools (Tools_A)" },
		{ value: "Tools_B", label: "Tools_B" },
	])
})

test("a box id that is no longer in the diagram stays selectable and is marked", () => {
	const options = toolBoxOptions(DIAGRAM, "Gone_1", translate)

	assert.deepEqual(options.at(-1), { value: "Gone_1", label: "Gone_1 (not in this diagram)" })
})
