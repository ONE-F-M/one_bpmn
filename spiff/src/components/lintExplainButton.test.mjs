import { test } from "node:test"
import assert from "node:assert/strict"
import { readFileSync } from "node:fs"
import { fileURLToPath } from "node:url"
import { dirname, join } from "node:path"

const here = dirname(fileURLToPath(import.meta.url))
const editor = readFileSync(join(here, "BpmnEditor.vue"), "utf8")

test("every lint entry gets an Explain this error button that asks ProsAlly", () => {
	assert.match(editor, /linting\._addEntry = function/)
	assert.match(editor, /bjsl-explain/)
	assert.match(editor, /explainLintFinding\(entry\)/)
})

test("the question avoids the fix-lint wording that routes to a diagram edit", () => {
	const message = editor.match(/`(Diagnose this lint finding[^`]*)`/)[1]
	assert.doesNotMatch(message, /\b(fix|resolve|clear|correct|repair)\b/i)
})
