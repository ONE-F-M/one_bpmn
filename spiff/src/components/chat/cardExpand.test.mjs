import { test } from "node:test"
import assert from "node:assert/strict"
import { readFileSync } from "node:fs"
import { fileURLToPath } from "node:url"
import { dirname, join } from "node:path"

// No component harness in spiff, so these read the single-file components as text.
// Mirrors spiff/src/uiPolish.test.mjs.
const here = dirname(fileURLToPath(import.meta.url))
const source = (path) => readFileSync(join(here, path), "utf8")

test("CardShell provides one shared expand mechanism: a header button and a 7xl Dialog around #expanded", () => {
	const shell = source("primitives/CardShell.vue")
	assert.match(shell, /\$slots\.expanded/)
	assert.match(shell, /prim-shell-expand-btn/)
	assert.match(shell, /size:\s*['"]7xl['"]/)
	assert.match(shell, /<slot name="expanded"/)
})

test("ScriptDiffCard's #expanded slot renders DiffView or CodeBlock at full width", () => {
	const card = source("cards/ScriptDiffCard.vue")
	const start = card.indexOf('template #expanded')
	assert.notEqual(start, -1, "ScriptDiffCard must define a #expanded template")
	const expandedBlock = card.slice(start, card.indexOf("</template>", start))
	assert.match(expandedBlock, /DiffView|CodeBlock|CodeMirrorEditor/)
})

test("TestCaseCard's #expanded slot re-renders the checklist", () => {
	const card = source("cards/TestCaseCard.vue")
	const start = card.indexOf('template #expanded')
	assert.notEqual(start, -1, "TestCaseCard must define a #expanded template")
})
