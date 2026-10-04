import { test } from "node:test"
import assert from "node:assert/strict"
import { readdirSync, readFileSync } from "node:fs"
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

test("DiagramPreviewCard offers an #expanded slot for its larger dialog view", () => {
	const card = source("components/chat/cards/DiagramPreviewCard.vue")
	assert.match(card, /<template #expanded>/)
	assert.match(card, /value\.summary/)
})

test("DiagramThumb takes a height prop instead of a hard-coded 180", () => {
	const thumb = source("components/chat/primitives/DiagramThumb.vue")
	assert.match(thumb, /height:\s*\{\s*type:\s*Number,\s*default:\s*180\s*\}/)
	assert.match(thumb, /new NavigatedViewer\(\{ container: host\.value, height: props\.height \}\)/)
	assert.doesNotMatch(thumb, /height:\s*180\s*\}\);/)
})

test("DiagramThumb's large prop removes the 190px thumbnail cap", () => {
	const thumb = source("components/chat/primitives/DiagramThumb.vue")
	assert.match(thumb, /large:\s*\{\s*type:\s*Boolean,\s*default:\s*false\s*\}/)
	assert.match(thumb, /max-height:\s*190px/)
	assert.match(thumb, /prim-thumb--large[^{]*\{\s*max-height:\s*none/)
})

test("DiagramThumb fits after layout and never leaks a viewer it was closed on", () => {
	const thumb = source("components/chat/primitives/DiagramThumb.vue")
	assert.match(thumb, /await nextTick\(\);\s*const canvas = viewer\.get\("canvas"\);\s*canvas\.resized\(\);/)
	assert.equal((thumb.match(/if \(disposed\) return;/g) || []).length, 2)
	assert.match(thumb, /disposed = true;/)
})

test("the expanded diagram offers zoom in, zoom out and fit; the chat thumbnail does not", () => {
	const thumb = source("components/chat/primitives/DiagramThumb.vue")
	assert.match(thumb, /v-if="large && ready" class="prim-thumb-zoom"/)
	assert.match(thumb, /@click="zoomBy\(ZOOM_STEP\)"/)
	assert.match(thumb, /@click="zoomBy\(1 \/ ZOOM_STEP\)"/)
	assert.match(thumb, /@click="fit"/)
	assert.match(thumb, /canvas\.zoom\(canvas\.zoom\(\) \* factor/)
})

test("every chat component whose template calls __ defines it; it is not a Vue global", () => {
	const dir = join(here, "components/chat")
	const files = readdirSync(dir, { recursive: true }).filter((f) => f.endsWith(".vue"))
	const missing = files.filter((f) => {
		const text = readFileSync(join(dir, f), "utf8")
		const template = text.slice(0, text.indexOf("<script"))
		return template.includes("__(") && !/const __ = /.test(text)
	})
	assert.deepEqual(missing, [])
})

test("the expanded diagram height is read on each open, not once", () => {
	const card = source("components/chat/cards/DiagramPreviewCard.vue")
	assert.match(card, /:height="expandedHeight\(\)"/)
	assert.doesNotMatch(card, /expandedHeight = computed/)
})
