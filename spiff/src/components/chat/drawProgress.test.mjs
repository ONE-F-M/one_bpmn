import { test } from "node:test"
import assert from "node:assert/strict"
import { readFileSync } from "node:fs"
import { fileURLToPath } from "node:url"
import { dirname, join } from "node:path"
import { progressLineFor } from "./drawProgress.js"

// No component harness in spiff, so the panel is read as text (as cardExpand.test.mjs does).
const here = dirname(fileURLToPath(import.meta.url))
const panel = readFileSync(join(here, "AgentChatPanel.vue"), "utf8")

test("the message of a onefm.progress value is the line shown", () => {
	assert.equal(progressLineFor({ phase: 2, total: 6, message: "Drawing part 2 of 6" }), "Drawing part 2 of 6")
	assert.equal(progressLineFor({ phase: 2, total: 6, message: "  Adding lanes  " }), "Adding lanes")
})

test("without a message, phase and total make the line", () => {
	assert.equal(progressLineFor({ phase: 3, total: 6 }), "Drawing part 3 of 6")
	assert.equal(progressLineFor({ phase: 3, total: 6, message: "  " }), "Drawing part 3 of 6")
	assert.equal(progressLineFor({ phase: 1, total: 2 }, (s) => `T:${s}`), "T:Drawing part 1 of 2".replace("T:", "T:"))
})

test("any other shape yields no line", () => {
	for (const bad of [null, undefined, "x", 5, [], {}, { phase: "2", total: 6 }, { phase: 0, total: 6 },
		{ phase: 7, total: 6 }, { phase: 1.5, total: 6 }, { message: 42 }]) {
		assert.equal(progressLineFor(bad), "")
	}
})

test("a very long message is cut so it cannot flood the panel", () => {
	assert.equal(progressLineFor({ message: "x".repeat(1000) }).length, 300)
})

test("the panel reads onefm.progress in handleCustom and never draws it as a card", () => {
	const branch = panel.match(/name === "onefm\.progress"\) \{[\s\S]*?return;\s*\}/)[0]
	assert.match(branch, /progressLineFor\(value, __\)/)
	// The branch sits before the transcript flush, so it adds nothing to items.
	assert.ok(panel.indexOf('name === "onefm.progress"') < panel.indexOf('name === "onefm.conversation_title"'))
})

test("the composer is locked and says why while a turn runs", () => {
	assert.match(panel, /<div v-if="busy" class="acp-locked-note"[^>]*>[\s\S]*?Still drawing/)
	assert.match(panel, /<textarea[\s\S]*?:disabled="busy"[\s\S]*?@keydown\.enter\.exact\.prevent="!busy && send\(\)"/)
	assert.match(panel, /<button class="acp-btn acp-btn--solid" :disabled="busy \|\| !draft\.trim\(\)" @click="!busy && send\(\)">/)
	// send() itself refuses while busy, so choice buttons and quick-sends cannot get past either.
	assert.match(panel, /if \(!message \|\| busy\.value\) return;/)
})

test("the lock lifts when the turn ends, and the progress line goes with it", () => {
	const done = panel.slice(panel.indexOf("onDone: () => {"), panel.indexOf("function handleEvent"))
	assert.match(done, /progressLine\.value = "";\s*busy\.value = false;/)
	// A failure ends through the client's finish(), which calls onDone after onError.
	const client = readFileSync(join(here, "aguiClient.js"), "utf8")
	assert.match(client, /const fail = \(text\) => \{[\s\S]*?onError && onError\(text\);\s*finish\(\);/)
})

test("progress lines wrap inside the panel and the page cannot scroll sideways", () => {
	const rule = panel.match(/\.acp-progress, \.acp-locked-note \{[^}]*\}/)[0]
	assert.match(rule, /min-width: 0/)
	assert.match(rule, /max-width: 100%/)
	assert.match(rule, /white-space: normal/)
	assert.match(rule, /overflow-wrap: anywhere/)
	assert.match(panel, /\.acp \{ min-width: 0; max-width: 100%; overflow-x: hidden; \}/)
	// The log must not clip: wide content scrolls inside it, which a 375px check in a browser confirmed.
	assert.doesNotMatch(panel, /\.acp-log \{ overflow-x: hidden; \}/)
})
