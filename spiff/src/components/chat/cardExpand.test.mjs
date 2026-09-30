import { test } from "node:test"
import assert from "node:assert/strict"
import { readFileSync } from "node:fs"
import { fileURLToPath } from "node:url"
import { dirname, join } from "node:path"

// No component harness in spiff, so these read the single-file components
// as text, following spiff/src/uiPolish.test.mjs's approach.
const here = dirname(fileURLToPath(import.meta.url))
const source = (path) => readFileSync(join(here, path), "utf8")

test("CardShell offers an #expanded dialog imported explicitly from frappe-ui", () => {
	const shell = source("primitives/CardShell.vue")
	assert.match(shell, /import\s*\{\s*Dialog\s*\}\s*from\s*"frappe-ui"/)
	assert.match(shell, /name="expanded"/)
	assert.match(shell, /size:\s*['"]7xl['"]/)
	// the maximize-2 button is gated behind $slots.expanded, so cards
	// without the slot show no button
	const buttonBlock = shell.slice(shell.indexOf("prim-shell-expand\""), shell.indexOf("</button>"))
	const beforeButton = shell.slice(0, shell.indexOf("prim-shell-expand\""))
	assert.match(beforeButton.slice(beforeButton.lastIndexOf("<button")), /v-if="\$slots\.expanded"/)
	assert.match(shell, /maximize-2/)
	assert.match(shell, /Open in larger window/)
	// the slot itself only mounts while the dialog is open
	assert.match(shell, /v-if="open"\s*name="expanded"/)
})

test("LuCrusherResultCard offers #expanded uncapped", () => {
	const card = source("cards/LuCrusherResultCard.vue")
	assert.match(card, /#expanded/)
	const body = source("cards/LuCrusherResultBody.vue")
	assert.match(body, /lcr-scroll-capped/)
	assert.doesNotMatch(body, /max-height:\s*220px[^}]*}\s*\n\.lcr-scroll-capped/)
})

test("ProposalCard offers #expanded with the same KeyValueTable", () => {
	const card = source("cards/ProposalCard.vue")
	assert.match(card, /#expanded/)
	assert.match(card, /<KeyValueTable :rows="rows" \/>/)
})

test("DataTableCard offers #expanded with the same DataTable at full width", () => {
	const card = source("cards/DataTableCard.vue")
	assert.match(card, /#expanded/)
	assert.match(card, /<DataTable/)
})
