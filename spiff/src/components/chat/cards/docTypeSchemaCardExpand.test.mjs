import { test } from "node:test"
import assert from "node:assert/strict"
import { readFileSync } from "node:fs"
import { fileURLToPath } from "node:url"
import { dirname, join } from "node:path"

// No component harness in spiff, so these read the single-file components
// as text (see ../../../uiPolish.test.mjs for the established pattern).
const here = dirname(fileURLToPath(import.meta.url))
const source = (path) => readFileSync(join(here, path), "utf8")

test("DocTypeSchemaCard offers an #expanded view with the fields and the raw JSON", () => {
	const card = source("DocTypeSchemaCard.vue")
	assert.match(card, /<template #expanded>/)
	const expanded = card.slice(card.indexOf("<template #expanded>"), card.indexOf("</template>", card.indexOf("<template #expanded>")))
	assert.match(expanded, /<FieldList\b/)
	assert.match(expanded, /<pre\b/)
	assert.match(expanded, /JSON\.stringify\(value\.doctype_ir, null, 2\)/)
	assert.doesNotMatch(expanded, /ActionButton|\$emit/)
})
