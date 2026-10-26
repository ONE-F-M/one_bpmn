import { test } from "node:test"
import assert from "node:assert/strict"
import { readFileSync } from "node:fs"
import { fileURLToPath } from "node:url"
import { dirname, join } from "node:path"

// No component harness in spiff, so this reads the single-file component as text.
const here = dirname(fileURLToPath(import.meta.url))
const source = (path) => readFileSync(join(here, path), "utf8")

test("ScriptDiffCard's #expanded renders the same diff or script, with no apply action", () => {
	const card = source("ScriptDiffCard.vue")
	const start = card.indexOf("<template #expanded>")
	assert.notEqual(start, -1, "ScriptDiffCard must define a #expanded template")
	const expanded = card.slice(start, card.indexOf("</template>", start))
	assert.match(expanded, /<DiffView v-if="value\.diff" :diff="value\.diff" \/>/)
	assert.match(expanded, /<CodeBlock v-else :code="value\.modified_script" \/>/)
	assert.doesNotMatch(expanded, /ActionButton|\$emit/)
})
