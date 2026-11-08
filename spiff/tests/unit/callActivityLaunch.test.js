import { test } from "vitest"
import assert from "node:assert/strict"
import { readFileSync } from "node:fs"
import { fileURLToPath } from "node:url"
import { dirname, join } from "node:path"

// No component harness in spiff, so this reads the single-file component as text.
const here = fileURLToPath(new URL("../../src/components/", import.meta.url))
const editor = readFileSync(join(here, "../composables/useEditorCanvas.js"), "utf8")
const editorCss = readFileSync(join(here, "Editor/BpmnEditor/BpmnEditor.css"), "utf8")

test("the drilldown arrow launches a Process-name link instead of the library alert", () => {
	const listener = editor.slice(editor.indexOf("const launchProcessNameLink"))
	const body = listener.slice(0, listener.indexOf("};"))
	assert.match(body, /closest\("\.bjs-drilldown"\)/)
	assert.match(body, /spiffworkflow:calledProcess/)
	assert.match(body, /event\.stopPropagation\(\)/)
	assert.match(body, /emit\("launch-callactivity-editor"/)
	assert.match(editor, /addEventListener\("click", launchProcessNameLink, true\)/)
})

test("the Process ID entry of the Called Element group is hidden", () => {
	assert.match(editorCss, /\.bio-properties-panel-entry\[data-entry-id="process_id"\]\s*\{\s*display:\s*none;/)
})
