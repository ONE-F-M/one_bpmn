<template>
	<div class="oa-root">
		<!-- ── history sidebar ─────────────────────────────────────────── -->
		<aside class="oa-sidebar">
			<button class="oa-new" @click="startNew">{{ __("New chat") }}</button>
			<div class="oa-sb-title">{{ __("Conversations") }}</div>
			<div
				v-for="c in conversations"
				:key="c.name"
				class="oa-sb-item"
				:class="{ active: c.name === activeConversation }"
				@click="open(c)"
			>
				<div class="oa-sb-item-title">{{ c.title || c.name }}</div>
				<div class="oa-sb-item-sub">{{ c.agent_mode }}</div>
			</div>
		</aside>

		<!-- ── the panel ───────────────────────────────────────────────── -->
		<div class="oa-main">
			<div class="oa-head">
				<select v-model="activeAgent" class="oa-picker" :title="__('Agent')">
					<option v-for="a in agents" :key="a.agent_id || a.value" :value="a.agent_id || a.value">
						{{ a.icon ? `${a.icon} ` : "" }}{{ a.label }}
					</option>
				</select>
			</div>
			<AgentChatPanel
				v-if="activeAgent"
				:key="panelKey"
				:agent-id="activeAgent"
				:conversation="activeConversation"
				variant="page"
				:cards="cardRegistry"
				:apply-targets="[]"
				allow-uploads
				@conversation="onConversation"
				@title="refreshList"
			/>
		</div>
	</div>
</template>

<script setup>
// one-ai (WI-001678) — the Lumina successor, hosted in one_bpmn. The page is
// deliberately thin: the history sidebar and the registry-driven agent
// picker are the only things the desk page owns; everything conversational
// is the same shared panel every other surface embeds. All modes ride the
// shared endpoint; onefm.conversation_title updates the header and the list.
import { onMounted, ref } from "vue";
import { frappeRequest } from "frappe-ui";
import AgentChatPanel from "./AgentChatPanel.vue";
import { cardRegistry } from "./cards/registry";

const __ = (window.__ && typeof window.__ === "function") ? window.__ : (s) => s;

const agents = ref([]);
const conversations = ref([]);
const activeAgent = ref("");
const activeConversation = ref("");
const panelKey = ref(0);

// agent_mode label → agent_id, so resuming a conversation picks its agent
const modeToAgent = ref({});

onMounted(async () => {
	try {
		const list = await frappeRequest({
			url: "/api/method/one_bpmn.api.agent_invocation.list_available_agents",
			params: { include_legacy: 0 },
		}) || [];
		agents.value = list;
		for (const a of list) if (a.value && a.agent_id) modeToAgent.value[a.value] = a.agent_id;
		if (list.length) activeAgent.value = list[0].agent_id || list[0].value;
	} catch (e) { /* empty picker renders; the page stays usable */ }
	refreshList();
});

async function refreshList() {
	try {
		conversations.value = await frappeRequest({
			url: "/api/method/one_bpmn.api.agui.list_conversations",
		}) || [];
	} catch (e) { /* sidebar just stays as-is */ }
}

function open(c) {
	activeConversation.value = c.name;
	const agent = modeToAgent.value[c.agent_mode];
	if (agent) activeAgent.value = agent;
	panelKey.value++; // remount so the panel resumes this conversation
}

function startNew() {
	activeConversation.value = "";
	panelKey.value++;
}

function onConversation(name) {
	activeConversation.value = name;
	refreshList();
}
</script>

<style scoped>
.oa-root { display: grid; grid-template-columns: 230px minmax(0, 1fr); height: calc(100vh - 120px);
	min-height: 480px; background: #fff; border: 1px solid #e2e2e2; border-radius: 12px; overflow: hidden; }
.oa-sidebar { border-right: 1px solid #e2e2e2; background: #f8f8f8; padding: 10px; overflow-y: auto; }
.oa-new { width: 100%; height: 28px; border: none; border-radius: 8px; background: #171717; color: #fff;
	font-size: 14px; cursor: pointer; margin-bottom: 12px; }
.oa-sb-title { font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.12em;
	color: #999; margin: 2px 4px 8px; }
.oa-sb-item { padding: 6px 9px; border-radius: 8px; margin-bottom: 2px; cursor: pointer; }
.oa-sb-item:hover { background: #ededed; }
.oa-sb-item.active { background: #ededed; }
.oa-sb-item-title { font-size: 12.5px; color: #383838; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.oa-sb-item-sub { font-size: 11px; color: #999; }
.oa-main { display: flex; flex-direction: column; min-width: 0; }
.oa-head { display: flex; align-items: center; padding: 8px 14px; border-bottom: 1px solid #e2e2e2; }
.oa-picker { height: 28px; border-radius: 8px; border: 1px solid #e2e2e2; background: #fff; font-size: 13px;
	color: #383838; padding: 0 8px; }
.oa-main :deep(.acp) { flex: 1; min-height: 0; }
:global([data-theme="dark"]) .oa-root { background: #1c1c1c; border-color: #343434; }
:global([data-theme="dark"]) .oa-sidebar { background: #232323; border-color: #343434; }
:global([data-theme="dark"]) .oa-new { background: #f8f8f8; color: #0f0f0f; }
:global([data-theme="dark"]) .oa-sb-item:hover, :global([data-theme="dark"]) .oa-sb-item.active { background: #343434; }
:global([data-theme="dark"]) .oa-sb-item-title { color: #d4d4d4; }
:global([data-theme="dark"]) .oa-head { border-color: #343434; }
:global([data-theme="dark"]) .oa-picker { background: #1c1c1c; border-color: #343434; color: #d4d4d4; }
</style>
