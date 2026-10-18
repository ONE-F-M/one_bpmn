import { test } from "node:test"
import assert from "node:assert/strict"
import { readFileSync } from "node:fs"
import { fileURLToPath } from "node:url"
import { dirname, join } from "node:path"

// WI-003579. spiff has no component harness (see chat/cardExpand.test.mjs), so
// these read the single-file components as text. The staging logic is small,
// so the script block of ProsAllyPanel is also executed against a stand-in
// for Vue's ref/computed, which checks what a turn would actually carry.
const here = dirname(fileURLToPath(import.meta.url))
const source = (path) => readFileSync(join(here, path), "utf8")
const panel = source("ProsAllyPanel.vue")
const chat = source("chat/AgentChatPanel.vue")

// The panel's choice/turn handlers, lifted from the real <script setup>.
function mountLogic() {
	const script = panel.match(/<script setup>([\s\S]*?)<\/script>/)[1]
	const body = script
		.replace(/^import .*$/gm, "")
		.replace(/const props = defineProps\([\s\S]*?\n\}\);/, "const props = { processName: 'P', diagramName: 'D', getCanvasXml: null };")
		.replace(/const emit = defineEmits\(.*\);/, "const emit = () => {};")
	const factory = new Function(
		"ref",
		"computed",
		"window",
		`${body}\nreturn { confirmedAction, turnContext, onChoice };`,
	)
	const ref = (value) => ({ value })
	const computed = (fn) => ({ get value() { return fn() } })
	const logic = factory(ref, computed, {})
	// the <template> wires these two events to the same reset
	const clearOn = (event) => new RegExp(`@${event}="confirmedAction = ''"`).test(panel)
	return { ...logic, clearOn }
}

test("ProsAllyPanel clears confirmed_action when the turn that carried it is sent", () => {
	assert.match(panel, /@turn-sent="confirmedAction = ''"/)
	// AgentChatPanel emits it after copying props.context, before streaming.
	const send = chat.slice(chat.indexOf("async function send("))
	const copied = send.indexOf("let turnContext = { ...props.context")
	const sentAt = send.indexOf('emit("turn-sent")')
	const streamAt = send.indexOf("streamAgentTurn({")
	assert.ok(copied > -1 && sentAt > copied && sentAt < streamAt)
	assert.match(chat, /defineEmits\(\[[^\]]*"turn-sent"/)
})

test("a real confirmation plus 'Yes, proceed' still sends confirmed_action on that turn", () => {
	const m = mountLogic()
	assert.equal(m.turnContext.value.confirmed_action, "")
	m.onChoice({ option: "Yes, proceed", actionIntent: "GENERATE_NEW" })
	// the context prop the panel copies in send() carries the approval
	assert.equal(m.turnContext.value.confirmed_action, "GENERATE_NEW")
})

test("after the confirmed send, a typed question goes without confirmed_action", () => {
	const m = mountLogic()
	m.onChoice({ option: "Yes, proceed", actionIntent: "GENERATE_NEW" })
	assert.equal(m.turnContext.value.confirmed_action, "GENERATE_NEW")
	// turn-sent fires once the context has been copied; its template handler
	// is the inline `confirmedAction = ''`, applied here as Vue would.
	assert.ok(m.clearOn("turn-sent"))
	m.confirmedAction.value = ""
	assert.equal(m.turnContext.value.confirmed_action, "")
})

test("a dismissive option never stages a confirmation", () => {
	const m = mountLogic()
	m.onChoice({ option: "No, let me adjust", actionIntent: "GENERATE_NEW" })
	assert.equal(m.turnContext.value.confirmed_action, "")
})

test("a failed or timed-out turn also emits turn-complete, so the next request is clean", () => {
	assert.match(panel, /@turn-complete="confirmedAction = ''"/)
	const onError = chat.slice(chat.indexOf("onError: (msg) => {"), chat.indexOf("onDone: () => {"))
	assert.match(onError, /sent\.failed = true/)
	assert.match(onError, /emit\("turn-complete"\)/)
	const onDone = chat.slice(chat.indexOf("onDone: () => {"), chat.indexOf("function handleEvent"))
	assert.match(onDone, /emit\("turn-complete"\)/)
})

test("choice buttons wrap inside the panel on a 390px phone and never cover the composer", () => {
	const opts = chat.match(/\.acp-card-opts \.acp-btn \{[^}]*\}/)[0]
	assert.match(opts, /height: auto/)
	assert.match(opts, /max-width: 100%/)
	assert.match(opts, /white-space: normal/)
	assert.match(chat, /\.acp-card-opts \{[^}]*flex-wrap: wrap/)
	const phone = chat.match(/@media \(max-width: 480px\) \{[\s\S]*?\n\}/)[0]
	assert.match(phone, /\.acp-card \{ width: 100%; \}/)
	assert.match(phone, /flex: 1 1 100%/)
})

test("each turn carries the lint findings the editor shows", () => {
	assert.match(panel, /getLintIssues: \{ type: Function, default: null \}/)
	assert.match(panel, /lint_issues: props\.getLintIssues \? await props\.getLintIssues\(\) : \[\]/)
	const editor = source("BpmnEditor.vue")
	assert.equal(editor.match(/:get-lint-issues="getLintIssues"/g).length, 2)
	assert.match(editor, /flattenLintIssues\(linting\._formatIssues\(await linting\.lint\(\)\)\)/)
})
