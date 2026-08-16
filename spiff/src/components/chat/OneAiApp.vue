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
				<span class="oa-brand">{{ __("ONE AI") }}</span>
				<select class="oa-picker" :title="__('Agent')" :value="activeAgent" @change="pickAgent($event.target.value)">
					<option v-for="a in agents" :key="a.agent_id || a.value" :value="a.agent_id || a.value">
						{{ a.icon ? `${a.icon} ` : "" }}{{ a.label }}
					</option>
				</select>
			</div>
			<div v-if="unavailable" class="oa-unavailable">
				{{ __("This conversation was held with") }} <b>{{ unavailable }}</b
				>{{ __(", which is not one of the agents available to you here. Open it from that agent's own surface, or start a new chat.") }}
			</div>
			<div v-else-if="loaded && !agents.length" class="oa-unavailable">
				{{ __("None of this page's agents are configured on this site yet.") }}
			</div>
			<AgentChatPanel
				v-else-if="activeAgent"
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
// deliberately thin: the history sidebar and the agent picker are the only
// things it owns; everything conversational is the same shared panel every
// other surface embeds. It offers the Lumina page's own fixed set of modes
// (General Chat, BA Agent, LuCrusher — see ONE_AI_AGENT_IDS) and lists only
// those conversations, so another surface's chats never appear here. All
// modes ride the shared endpoint; onefm.conversation_title updates the
// header and the list.
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
// Set when a history item belongs to an agent this page cannot run — the
// conversation is NOT opened in that case (see open()).
const unavailable = ref("");
const loaded = ref(false); // the agent list has come back (empty state vs. still loading)

// agent_mode label → agent_id, so resuming a conversation picks its agent
const modeToAgent = ref({});

onMounted(async () => {
	try {
		// The page offers Lumina's own modes and nothing else — the fixed list
		// lives on the server (ONE_AI_AGENT_IDS), not here, so the picker and
		// the sidebar filter can never disagree.
		const list = await frappeRequest({
			url: "/api/method/one_bpmn.api.agent_invocation.list_one_ai_agents",
		}) || [];
		agents.value = list;
		// A conversation stores agent_mode, which is the chat_mode_label for
		// most rows but the bare agent_id for others — index both, or opening
		// such a conversation silently resumes it under whichever agent the
		// picker happens to show (seen live 2026-08-16).
		for (const a of list) {
			if (a.agent_id) {
				if (a.value) modeToAgent.value[a.value] = a.agent_id;
				modeToAgent.value[a.agent_id] = a.agent_id;
			}
		}
		if (list.length) activeAgent.value = list[0].agent_id || list[0].value;
	} catch (e) { /* empty picker renders; the page stays usable */ } finally {
		loaded.value = true;
	}
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
	const agent = modeToAgent.value[c.agent_mode];
	if (!agent) {
		// Refusing to open beats opening it under the wrong agent: the next
		// message would go to whoever the picker shows, carrying someone
		// else's transcript.
		activeConversation.value = c.name;
		unavailable.value = c.agent_mode || __("an unknown agent");
		return;
	}
	unavailable.value = "";
	activeConversation.value = c.name;
	activeAgent.value = agent;
	panelKey.value++; // remount so the panel resumes this conversation
}

// Switching agent starts a fresh conversation. Keeping the open one would
// hand the next turn to a different agent under the same conversation id —
// the same cross-agent contamination the legacy page avoided by LOCKING its
// mode dropdown once a conversation had messages.
function pickAgent(agentId) {
	if (agentId === activeAgent.value) return;
	activeAgent.value = agentId;
	startNew();
}

function startNew() {
	activeConversation.value = "";
	unavailable.value = "";
	panelKey.value++;
}

function onConversation(name) {
	activeConversation.value = name;
	refreshList();
}
</script>

<style scoped>
/* The host owns the box: the standalone /one-ai page gives it the whole
   viewport, an embedding host gives it whatever it has (WI-001678).
   grid-template-rows is load-bearing: an implicit row is auto-sized, so it
   grew to the transcript's full height, the panel's `height: 100%` followed
   the ROW rather than this box, and the log never became scrollable — a long
   conversation pushed the composer thousands of pixels below a viewport that
   would not scroll (reported 2026-08-16). box-sizing keeps the 1px border
   inside the 100%, which was overflowing the page by 2px. */
.oa-root { display: grid; grid-template-columns: 230px minmax(0, 1fr);
	grid-template-rows: minmax(0, 1fr); box-sizing: border-box; height: 100%;
	min-height: 480px; background: #fff; border: 1px solid #e2e2e2; overflow: hidden; }
/* min-height: 0 on both columns — a grid item's automatic minimum size is
   its content, which would defeat the bounded row above. */
.oa-sidebar { border-right: 1px solid #e2e2e2; background: #f8f8f8; padding: 10px;
	overflow-y: auto; min-height: 0; }
.oa-new { width: 100%; height: 28px; border: none; border-radius: 8px; background: #171717; color: #fff;
	font-size: 14px; cursor: pointer; margin-bottom: 12px; }
.oa-sb-title { font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.12em;
	color: #999; margin: 2px 4px 8px; }
.oa-sb-item { padding: 6px 9px; border-radius: 8px; margin-bottom: 2px; cursor: pointer; }
.oa-sb-item:hover { background: #ededed; }
.oa-sb-item.active { background: #ededed; }
.oa-sb-item-title { font-size: 12.5px; color: #383838; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.oa-sb-item-sub { font-size: 11px; color: #999; }
.oa-main { display: flex; flex-direction: column; min-width: 0; min-height: 0; }
.oa-head { display: flex; align-items: center; gap: 10px; padding: 8px 14px; border-bottom: 1px solid #e2e2e2; }
.oa-brand { font-size: 13px; font-weight: 600; color: #171717; }
.oa-picker { height: 28px; border-radius: 8px; border: 1px solid #e2e2e2; background: #fff; font-size: 13px;
	color: #383838; padding: 0 8px; }
.oa-main :deep(.acp) { flex: 1; min-height: 0; }
.oa-unavailable { margin: 16px; padding: 10px 12px; border: 1px solid #e2e2e2; border-radius: 8px;
	font-size: 12.5px; color: #525252; background: #f8f8f8; }
:global([data-theme="dark"]) .oa-root { background: #1c1c1c; border-color: #343434; }
:global([data-theme="dark"]) .oa-sidebar { background: #232323; border-color: #343434; }
:global([data-theme="dark"]) .oa-new { background: #f8f8f8; color: #0f0f0f; }
:global([data-theme="dark"]) .oa-sb-item:hover, :global([data-theme="dark"]) .oa-sb-item.active { background: #343434; }
:global([data-theme="dark"]) .oa-sb-item-title { color: #d4d4d4; }
:global([data-theme="dark"]) .oa-head { border-color: #343434; }
:global([data-theme="dark"]) .oa-brand { color: #f8f8f8; }
:global([data-theme="dark"]) .oa-unavailable { background: #232323; border-color: #343434; color: #999; }
:global([data-theme="dark"]) .oa-picker { background: #1c1c1c; border-color: #343434; color: #d4d4d4; }
</style>
