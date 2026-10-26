import { test } from "node:test"
import assert from "node:assert/strict"
import { readFileSync } from "node:fs"
import { fileURLToPath } from "node:url"
import { dirname, join } from "node:path"

// No component harness in spiff, so these read the single-file components
// as text, following spiff/src/uiPolish.test.mjs's approach.
const here = dirname(fileURLToPath(import.meta.url))
const source = (path) => readFileSync(join(here, path), "utf8")

test("CardShell opens #expanded in its own teleported window, above every chat host", () => {
	const shell = source("primitives/CardShell.vue")
	// The button exists only for cards that fill #expanded.
	assert.match(shell, /<button\s+v-if="\$slots\.expanded"/)
	assert.match(shell, /Open in larger window/)
	// Self-contained: frappe-ui's Dialog is unstyled in the one-ai bundle and
	// pinned to z-index 50 in the SPA.
	assert.doesNotMatch(shell, /from "frappe-ui"/)
	assert.match(shell, /<Teleport v-if="\$slots\.expanded" to="body">/)
	// Mounted only while open, so a heavy body never exists twice at rest.
	assert.match(shell, /<div v-if="open" class="prim-shell-scrim"[\s\S]*<slot name="expanded" \/>/)
	const z = Number(shell.match(/\.prim-shell-scrim \{[^}]*z-index: (\d+)/)[1])
	assert.ok(z > 10000, "must sit above LogixChat's apply dialog (10000)")
	// Escape closes this window only, not the host underneath.
	assert.match(shell, /addEventListener\("keydown", onKeydown, true\)/)
	assert.match(shell, /stopImmediatePropagation\(\)/)
})

test("LuCrusherResultCard offers #expanded uncapped and read-only", () => {
	const card = source("cards/LuCrusherResultCard.vue")
	assert.match(card, /<template v-if="view\.panel" #expanded>\s*<LuCrusherResultBody[^>]*\breadonly\b/)
	assert.doesNotMatch(card.slice(card.indexOf("#expanded")), /@action/)
	const body = source("cards/LuCrusherResultBody.vue")
	const scroll = body.match(/\.lcr-scroll \{[^}]*\}/)[0]
	assert.doesNotMatch(scroll, /max-height/)
	assert.match(body, /\.lcr-scroll-capped \{ max-height: 220px/)
	// Every quick-send is kept off the expanded copy.
	assert.match(body, /<ActionButton v-if="!readonly" :label="__\('Select'\)"/)
	assert.match(body, /view\.stageActions\.length && !view\.confirmed && !readonly/)
	assert.match(body, /view\.suggestions\.length && !readonly/)
})

test("ProposalCard offers #expanded with the same KeyValueTable", () => {
	const card = source("cards/ProposalCard.vue")
	assert.match(card, /#expanded/)
	assert.match(card, /<KeyValueTable :rows="rows" \/>/)
})

test("DataTableCard offers #expanded with the same DataTable and no row actions", () => {
	const card = source("cards/DataTableCard.vue")
	const expanded = card.slice(card.indexOf("#expanded"), card.indexOf("</template>", card.indexOf("#expanded")))
	assert.match(expanded, /<DataTable :columns="value\.columns" :rows="value\.rows" \/>/)
	assert.doesNotMatch(expanded, /row-action/)
	assert.match(card, /<template v-if="value\.rows && value\.rows\.length" #expanded>/)
})
