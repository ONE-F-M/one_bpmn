import { test } from "vitest"
import assert from "node:assert/strict"
import { readFileSync } from "node:fs"
import { fileURLToPath } from "node:url"
import { dirname, join } from "node:path"

const here = fileURLToPath(new URL("../../src/components/", import.meta.url))
const editor = readFileSync(join(here, "../composables/Editor/useEditorLint.js"), "utf8")

test("every lint entry gets an Explain this error button that asks ProsAlly", () => {
	assert.match(editor, /linting\._addEntry = function/)
	assert.match(editor, /bjsl-explain/)
	assert.match(editor, /explainLintFinding\(entry\)/)
})

test("lint details stay open on icon click and close on outside click", () => {
	assert.match(editor, /get\("canvas"\)\._container\.addEventListener\("click"/)
	assert.match(editor, /closest\("\.bjsl-icon"\)/)
	assert.match(editor, /classList\.add\("open"\)/)
	assert.match(editor, /classList\.remove\("open"\)/)
	assert.match(editor, /document\.addEventListener\("click"/)
	assert.match(editor, /closest\("\.bjsl-overlay"\)/)
})

test("the outside-click listener is removed when the diagram is destroyed", () => {
	assert.match(editor, /document\.addEventListener\("click", closeLintDetails\)/)
	assert.match(editor, /eventBus\.on\("diagram\.destroy"[\s\S]*?document\.removeEventListener\("click", closeLintDetails\)/)
})

test("the question avoids the fix-lint wording that routes to a diagram edit", () => {
	const message = editor.match(/`(Diagnose this lint finding[^`]*)`/)[1]
	assert.doesNotMatch(message, /\b(fix|resolve|clear|correct|repair)\b/i)
})
