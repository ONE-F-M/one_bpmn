import { test } from "node:test"
import assert from "node:assert/strict"
import { readFileSync } from "node:fs"
import { fileURLToPath } from "node:url"
import { dirname, join } from "node:path"

// spiff has no component harness, so these read the single-file components as text.
const here = dirname(fileURLToPath(import.meta.url))
const source = (path) => readFileSync(join(here, path), "utf8")
const card = source("cards/DiagramPreviewCard.vue")
const thumb = source("primitives/DiagramThumb.vue")

test("the preview card opens the sub-process the reply names, in the chat thumbnail and the expanded view", () => {
	const thumbs = card.match(/<DiagramThumb\b[^>]*>/g)
	assert.equal(thumbs.length, 2)
	for (const tag of thumbs) assert.match(tag, /:root-id="value\.scope_id"/)
})

test("the thumbnail opens the plane drawn for that sub-process once the diagram is imported", () => {
	assert.match(thumb, /rootId: \{ type: String, default: "" \}/)
	assert.match(thumb, /bpmnElement\?\.id === props\.rootId/)
	assert.ok(thumb.indexOf("viewer.open(plane)") > thumb.indexOf("viewer.importXML("))
	assert.ok(thumb.indexOf("viewer.open(plane)") < thumb.indexOf("\t\tfit();"))
})
