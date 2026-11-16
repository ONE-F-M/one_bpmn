// The unsent composer draft, kept per agent and conversation in this browser across a reload.
import { onMounted, ref, watch } from "vue";

const PREFIX = "acp-draft:";

export function useChatDraft(keyFn) {
	const draft = ref("");
	onMounted(() => {
		draft.value = loadDraft(keyFn());
	});
	watch(draft, () => saveDraft(keyFn(), draft.value));
	return draft;
}

export function chatDraftKey(agentId, conversation) {
	return `${PREFIX}${agentId || ""}:${conversation || ""}`;
}

export function loadDraft(key, storage = globalThis.localStorage) {
	return storage?.getItem(key) || "";
}

export function saveDraft(key, text, storage = globalThis.localStorage) {
	if (text) storage?.setItem(key, text);
	else storage?.removeItem(key);
}
