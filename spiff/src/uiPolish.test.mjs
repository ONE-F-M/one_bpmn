import { test } from "node:test"
import assert from "node:assert/strict"
import { readFileSync } from "node:fs"
import { fileURLToPath } from "node:url"
import { dirname, join } from "node:path"

// No component harness in spiff, so these read the single-file components as text.
const here = dirname(fileURLToPath(import.meta.url))
const source = (path) => readFileSync(join(here, path), "utf8")

test("the editor's folded formatting tools open from a palette icon, not an ellipsis", () => {
	const editor = source("components/BpmnEditor.vue")
	const button = editor.slice(editor.indexOf("bpmn-toolbar-more p-1.5") - 300, editor.indexOf("bpmn-toolbar-more p-1.5") + 400)
	assert.match(button, /title="Formatting"/)
	assert.match(button, /lucide:palette/)
	assert.doesNotMatch(button, /lucide:ellipsis/)
})

test("locking the property panel announces itself once; a finished redeploy adds no second notice", () => {
	const editor = source("views/Editor.vue")
	const finalize = editor.slice(editor.indexOf("async function finalizeReassignments"))
	const body = finalize.slice(0, finalize.indexOf("\n}\n"))
	assert.match(body, /Changes saved, redeploy pending/)
	assert.doesNotMatch(body, /"green"/)
})

test("the allocation donut animates in like the Usage donut", () => {
	assert.doesNotMatch(source("components/insights/CostAllocationDonut.vue"), /animation:\s*false/)
	assert.doesNotMatch(source("components/insights/UsageReportDonut.vue"), /animation:\s*false/)
})
