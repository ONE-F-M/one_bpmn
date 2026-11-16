import { test } from "vitest"
import assert from "node:assert/strict"
import { readFileSync } from "node:fs"
import { fileURLToPath } from "node:url"
import { chatDraftKey, loadDraft, saveDraft } from "../../src/composables/useChatDraft.js"

const panel = readFileSync(
	fileURLToPath(new URL("../../src/components/Chat/AgentChatPanel/AgentChatPanel.vue", import.meta.url)),
	"utf8",
)

function fakeStorage() {
	const map = new Map()
	return {
		getItem: (k) => (map.has(k) ? map.get(k) : null),
		setItem: (k, v) => map.set(k, String(v)),
		removeItem: (k) => map.delete(k),
		map,
	}
}

test("a draft survives a reload for the same agent and conversation", () => {
	const storage = fakeStorage()
	const key = chatDraftKey("lucrusher_agent", "0he1jdqhp3")
	saveDraft(key, "Generate ProsAlly Prompt", storage)
	assert.equal(loadDraft(key, storage), "Generate ProsAlly Prompt")
	assert.equal(loadDraft(chatDraftKey("lucrusher_agent", "other"), storage), "")
})

test("an emptied draft leaves nothing behind", () => {
	const storage = fakeStorage()
	const key = chatDraftKey("a", "c")
	saveDraft(key, "x", storage)
	saveDraft(key, "", storage)
	assert.equal(storage.map.size, 0)
})

test("no storage at all reads as no draft", () => {
	assert.equal(loadDraft("k", undefined), "")
	saveDraft("k", "x", undefined)
})

test("the chat panel's draft is the composable's ref, keyed by agent and live conversation", () => {
	assert.match(panel, /const draft = useChatDraft\(\(\) => chatDraftKey\(props\.agentId, conversationName\.value\)\);/)
	const send = panel.slice(panel.indexOf("async function send("))
	assert.ok(send.indexOf('draft.value = "";') < send.indexOf("streamAgentTurn({"))
})
