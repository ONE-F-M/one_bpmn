<template>
	<div class="acp" :class="`acp--${variant}`">
		<!-- ── header ─────────────────────────────────────────────────── -->
		<div class="acp-head">
			<div class="acp-avatar">{{ avatarInitials }}</div>
			<div class="acp-title">{{ conversationTitle || surface.label || agentId }}</div>
			<span v-if="modeChip" class="acp-chip acp-chip--blue">{{ modeChip }}</span>
			<span v-if="surfaceBadge" class="acp-chip acp-chip--right">{{ surfaceBadge }}</span>
			<slot name="header-actions" />
		</div>

		<!-- ── transcript ─────────────────────────────────────────────── -->
		<div ref="log" class="acp-log">
			<template v-for="(item, i) in items" :key="i">
				<!-- plain text bubbles -->
				<div v-if="item.kind === 'user'" class="acp-msg acp-msg--user">{{ item.text }}<span v-if="item.file" class="acp-filechip">📎 {{ item.file }}</span></div>
				<div
					v-else-if="item.kind === 'agent'"
					class="acp-msg acp-msg--agent"
					v-html="renderMarkdown(item.text)"
				/>
				<!-- choice buttons (panel feature, onefm.choice) -->
				<div v-else-if="item.kind === 'choice'" class="acp-card">
					<div class="acp-card-head">{{ item.value.prompt }}</div>
					<div class="acp-card-opts">
						<button
							v-for="opt in item.value.options"
							:key="opt"
							class="acp-btn acp-btn--subtle"
							:disabled="busy || item.answered"
							:class="{ 'acp-btn--solid': item.answered === opt }"
							@click="answerChoice(item, opt)"
						>
							{{ opt }}
						</button>
					</div>
				</div>
				<!-- registered card (registry arrives with WI-001673) -->
				<component
					:is="cards[item.name]"
					v-else-if="item.kind === 'custom' && cards[item.name]"
					:value="item.value"
					:busy="busy"
					:done="!!item.doneAction"
					:done-action="item.doneAction || ''"
					:surface-type="surface.surface_type"
					:artifact-type="surface.artifact_type"
					@action="(action, payload) => onCardAction(item, action, payload)"
				/>
				<!-- safe fallback: unknown custom events never break the transcript -->
				<div v-else-if="item.kind === 'custom'" class="acp-card">
					<div class="acp-card-head acp-card-head--muted">{{ item.name }}</div>
					<details class="acp-fallback">
						<summary>{{ __("Details") }}</summary>
						<pre>{{ JSON.stringify(item.value, null, 2) }}</pre>
					</details>
				</div>
			</template>

			<div v-if="busy" class="acp-thinking">{{ streamingText ? "" : __("Thinking…") }}</div>
			<div v-if="streamingText" class="acp-msg acp-msg--agent" v-html="renderMarkdown(streamingText)" />
			<div v-if="statusLine" class="acp-status">
				<span class="acp-dot" :class="{ 'acp-dot--err': status === 'error' }" />{{ statusLine }}
			</div>

			<!-- starter prompts on an empty conversation -->
			<div v-if="showStarters" class="acp-starters">
				<button
					v-for="p in surface.sample_prompts"
					:key="p"
					class="acp-btn acp-btn--outline"
					@click="draft = p"
				>
					{{ p }}
				</button>
			</div>
		</div>

		<!-- ── composer ───────────────────────────────────────────────── -->
		<div class="acp-toolbar">
			<button class="acp-tb" :title="__('Bold')" @click="wrapSelection('**')"><b>B</b></button>
			<button class="acp-tb" :title="__('Italic')" @click="wrapSelection('*')"><i>I</i></button>
			<button class="acp-tb" :title="__('List')" @click="prefixLine('- ')">≣</button>
		</div>
		<div v-if="pendingFile" class="acp-pending-file">
			<span class="acp-filechip">📎 {{ pendingFile.file_name }}</span>
			<button class="acp-tb" :title="__('Remove')" @click="pendingFile = null">✕</button>
		</div>
		<div class="acp-composer">
			<button
				v-if="allowUploads"
				class="acp-btn acp-btn--outline"
				:disabled="busy || uploading"
				:title="__('Attach a file')"
				@click="fileInput && fileInput.click()"
			>
				{{ uploading ? "…" : "📎" }}
			</button>
			<input ref="fileInput" type="file" class="acp-hidden" @change="onFilePicked" />
			<textarea
				ref="input"
				v-model="draft"
				class="acp-input"
				rows="1"
				:placeholder="surface.composer_placeholder || __('Type a message…')"
				:disabled="busy"
				@keydown.enter.exact.prevent="send()"
			/>
			<button class="acp-btn acp-btn--solid" :disabled="busy || !draft.trim()" @click="send()">
				{{ __("Send") }}
			</button>
		</div>

		<Dialog v-model="errorOpen" :options="{ title: __('Something went wrong'), size: 'sm' }">
			<template #body-content>
				<p class="acp-error-text">{{ errorMessage }}</p>
			</template>
		</Dialog>
	</div>
</template>

<script setup>
// Shared AgentChatPanel (WI-001672) — one chat window for every agent.
//
// The panel is agent-agnostic: label, icon, greeting, placeholder and
// starter prompts come from AI Agent Configuration via get_agent_surface
// (WI-001996); events arrive from the shared endpoint via aguiClient
// (WI-001670); anything card-shaped renders through the `cards` registry
// prop (WI-001673) or the safe fallback. Cards render and request — the
// HOST applies: card actions re-emit upward as `card-action`.
//
// Lifecycle: resume-or-create. Given a conversation, prior turns load
// before the composer activates; without one, the first send creates it
// (the id arrives on RUN_STARTED as thread_id). Unmount ends the
// conversation — the fix for this week's orphaned Active instances.
import MarkdownIt from "markdown-it";
import { Dialog, frappeRequest } from "frappe-ui";
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { streamAgentTurn } from "./aguiClient";

const props = defineProps({
	agentId: { type: String, required: true },
	conversation: { type: String, default: "" },
	context: { type: Object, default: () => ({}) },
	variant: { type: String, default: "docked" }, // docked | modal | page
	// host context line appended under the configured greeting
	hostContextLine: { type: String, default: "" },
	// event name → card component (WI-001673 registry)
	cards: { type: Object, default: () => ({}) },
	// async host hook called at send time; its result merges over `context`
	// (WI-001675: live canvas XML must be read per turn, not at mount)
	contextProvider: { type: Function, default: null },
	// WI-001678: file uploads (one-ai parity). The file uploads through
	// frappe's standard upload_file and its file_url rides the next turn's
	// context — the transport itself stays a plain SSE GET.
	allowUploads: { type: Boolean, default: false },
});

const emit = defineEmits(["card-action", "conversation", "title", "choice", "turn-complete"]);

const __ = (window.__ && typeof window.__ === "function") ? window.__ : (s) => s;

const md = new MarkdownIt({ html: false, linkify: true, breaks: true });

const surface = ref({});
const items = ref([]);
const draft = ref("");
const busy = ref(false);
const status = ref("idle");
const streamingText = ref("");
const conversationName = ref(props.conversation || "");
const conversationTitle = ref("");
const modeChip = ref("");
const errorOpen = ref(false);
const errorMessage = ref("");
const log = ref(null);
const input = ref(null);

// The composer grows with its content (up to ~6 lines) and shrinks back
// after a send — a fixed-height textarea hides everything above the last
// line the moment Shift+Enter adds a second one.
watch(draft, () => {
	nextTick(() => {
		const el = input.value;
		if (!el) return;
		el.style.height = "auto";
		el.style.height = `${Math.min(el.scrollHeight, 132)}px`;
	});
});
let activeStream = null;

const avatarInitials = computed(() => {
	if (surface.value.icon) return surface.value.icon;
	const label = surface.value.label || props.agentId || "?";
	return label.replace(/[^A-Za-z ]/g, "").split(/\s+/).map((w) => w[0]).join("").slice(0, 2).toUpperCase() || "?";
});
// The header badge is configuration, not code: chat_description verbatim
// when the agent has one, else a human descriptor of its surface_type —
// how this agent hands work over (WI-001996).
const surfaceBadge = computed(() => {
	if (surface.value.description) return surface.value.description;
	return {
		Document: __("proposes changes you review, then apply"),
		Form: __("fills in fields for you to confirm"),
	}[surface.value.surface_type] || "";
});
const showStarters = computed(
	() => !busy.value && (surface.value.sample_prompts || []).length && !items.value.some((i) => i.kind === "user")
);
const statusLine = computed(() => {
	if (status.value === "done") return __("Done");
	if (status.value === "error") return __("Failed — see the message above");
	return "";
});

function renderMarkdown(text) {
	return md.render(text || "");
}

function scrollDown() {
	nextTick(() => {
		if (log.value) log.value.scrollTop = log.value.scrollHeight;
	});
}

// ── lifecycle: resume-or-create ─────────────────────────────────────────────

onMounted(async () => {
	try {
		surface.value = await frappeRequest({
			url: "/api/method/one_bpmn.api.agent_invocation.get_agent_surface",
			params: { agent_id: props.agentId },
		}) || {};
	} catch (e) {
		surface.value = { label: props.agentId };
	}

	if (conversationName.value) {
		try {
			const history = await frappeRequest({
				url: "/api/method/one_bpmn.api.agui.conversation_history",
				params: { conversation: conversationName.value },
			}) || [];
			for (const m of history) {
				items.value.push({ kind: m.role === "user" ? "user" : "agent", text: m.content });
			}
		} catch (e) {
			/* an unreadable conversation resumes as empty, never as an error */
		}
	}

	if (!items.value.length) {
		const greeting = [surface.value.greeting, props.hostContextLine].filter(Boolean).join("\n\n");
		if (greeting) items.value.push({ kind: "agent", text: greeting });
	}
	scrollDown();
});

onBeforeUnmount(() => {
	if (activeStream) activeStream.close();
	if (conversationName.value) {
		// fire-and-forget: safe to call repeatedly, never raises (staging contract)
		frappeRequest({
			url: "/api/method/one_bpmn.api.server_script_api.end_chat_conversation",
			params: { conversation_name: conversationName.value },
		}).catch(() => {});
	}
});

// ── uploads (WI-001678) ─────────────────────────────────────────────────────

const pendingFile = ref(null); // { file_url, file_name }
const uploading = ref(false);
const fileInput = ref(null);

async function onFilePicked(event) {
	const file = event.target.files && event.target.files[0];
	if (!file) return;
	uploading.value = true;
	try {
		const body = new FormData();
		body.append("file", file);
		body.append("is_private", "0");
		const res = await fetch("/api/method/upload_file", {
			method: "POST",
			headers: { "X-Frappe-CSRF-Token": window.csrf_token || "" },
			body,
			credentials: "include",
		});
		const data = await res.json();
		const url = data.message && data.message.file_url;
		if (url) pendingFile.value = { file_url: url, file_name: file.name };
	} catch (e) {
		errorMessage.value = __("The file could not be uploaded.");
		errorOpen.value = true;
	} finally {
		uploading.value = false;
		if (fileInput.value) fileInput.value.value = "";
	}
}

// ── sending ─────────────────────────────────────────────────────────────────

async function send(text) {
	const message = (text ?? draft.value).trim();
	if (!message || busy.value) return;
	draft.value = "";
	items.value.push({ kind: "user", text: message });
	busy.value = true;
	status.value = "streaming";
	streamingText.value = "";
	scrollDown();

	let turnContext = { ...props.context };
	if (pendingFile.value) {
		turnContext.file = pendingFile.value.file_url;
		items.value[items.value.length - 1].file = pendingFile.value.file_name;
		pendingFile.value = null;
	}
	if (props.contextProvider) {
		try {
			turnContext = { ...turnContext, ...((await props.contextProvider()) || {}) };
		} catch (e) {
			/* a failing provider must not block the turn */
		}
	}

	activeStream = streamAgentTurn({
		agentId: props.agentId,
		message,
		conversation: conversationName.value || undefined,
		context: turnContext,
		onEvent: handleEvent,
		onError: (msg) => {
			status.value = "error";
			errorMessage.value = msg;
			errorOpen.value = true;
		},
		onDone: () => {
			if (streamingText.value) {
				items.value.push({ kind: "agent", text: streamingText.value });
				streamingText.value = "";
			}
			busy.value = false;
			if (status.value !== "error") status.value = "done";
			activeStream = null;
			emit("turn-complete");
			scrollDown();
		},
	});
}

function handleEvent(event) {
	const type = (event.type || "").toUpperCase();
	if (type === "RUN_STARTED") {
		if (event.threadId || event.thread_id) {
			const conv = event.threadId || event.thread_id;
			if (conv !== conversationName.value) {
				conversationName.value = conv;
				emit("conversation", conv);
			}
		}
	} else if (type === "TEXT_MESSAGE_CONTENT") {
		streamingText.value += event.delta || "";
		scrollDown();
	} else if (type === "CUSTOM") {
		handleCustom(event.name || "", event.value || {});
	}
	// TEXT_MESSAGE_START/END, THINKING_*, TOOL_CALL_*, STATE_* need no
	// transcript entry today; the streaming buffer covers the visible part.
}

function handleCustom(name, value) {
	// flush any streamed text so events land after the words they follow
	if (streamingText.value) {
		items.value.push({ kind: "agent", text: streamingText.value });
		streamingText.value = "";
	}
	if (name === "onefm.conversation_title") {
		conversationTitle.value = value.title || "";
		emit("title", conversationTitle.value);
	} else if (name === "onefm.mode_transition") {
		modeChip.value = value.new_mode || "";
	} else if (name === "onefm.choice") {
		items.value.push({ kind: "choice", value, answered: "" });
	} else {
		items.value.push({ kind: "custom", name, value });
	}
	scrollDown();
}

function answerChoice(item, option) {
	item.answered = option;
	// Synchronous emit BEFORE the send: the host can stage per-turn context
	// (e.g. ProsAlly's confirmed_action) and the send below reads it.
	emit("choice", { option, actionIntent: item.value.action_intent || "" });
	send(option);
}

function onCardAction(item, action, payload) {
	// A decision made retires the card's buttons (WI-001673 done-state):
	// the host applies exactly once, and a stale card cannot re-fire.
	item.doneAction = action;
	emit("card-action", { name: item.name, action, value: item.value, payload });
}

// ── composer toolbar (markdown markers, kept deliberately simple) ───────────

function wrapSelection(marker) {
	const el = input.value;
	if (!el) return;
	const { selectionStart: a, selectionEnd: b } = el;
	draft.value = draft.value.slice(0, a) + marker + draft.value.slice(a, b) + marker + draft.value.slice(b);
	nextTick(() => el.focus());
}

function prefixLine(prefix) {
	draft.value = draft.value ? `${draft.value}\n${prefix}` : prefix;
	nextTick(() => input.value && input.value.focus());
}

defineExpose({ send, conversationName });
</script>

<style scoped>
/* frappe-ui semantic tokens (helpdesk gray scheme — decided 2026-08-07),
   light and dark, matching the design-guide mockups. */
.acp {
	--sw: #fff; --sg1: #f8f8f8; --sg2: #f3f3f3; --sg3: #ededed; --sg4: #e2e2e2; --sg7: #171717;
	--iw: #fff; --ig9: #171717; --ig8: #383838; --ig6: #525252; --ig5: #7c7c7c; --ig4: #999;
	--og1: #ededed; --og2: #e2e2e2; --blue-bg: #e6f4ff; --blue-ink: #007be0;
	--green-ink: #278f5e; --red-ink: #cc2929;
	display: flex; flex-direction: column; min-height: 0; background: var(--sw);
	color: var(--ig8); font-size: 13px;
}
:global([data-theme="dark"]) .acp { --sw: #1c1c1c; --sg1: #232323; --sg2: #2b2b2b; --sg3: #343434; --sg4: #424242; --sg7: #f8f8f8;
		--iw: #0f0f0f; --ig9: #f8f8f8; --ig8: #d4d4d4; --ig6: #999; --ig5: #808080; --ig4: #717171;
		--og1: #232323; --og2: #343434; --blue-bg: #052b53; --blue-ink: #5aaef2;
		--green-ink: #58c08e; --red-ink: #fc7474; }
.acp--docked { height: 100%; border-left: 1px solid var(--og2); }
.acp--modal { height: 520px; }
.acp--page { height: 100%; }

.acp-head { display: flex; align-items: center; gap: 8px; padding: 9px 14px; border-bottom: 1px solid var(--og2); }
.acp-avatar { width: 24px; height: 24px; border-radius: 99px; background: var(--sg3); color: var(--ig6);
	display: grid; place-items: center; font-size: 10px; font-weight: 600; flex: none; }
.acp-title { font-weight: 600; color: var(--ig9); }
.acp-chip { margin-left: auto; height: 20px; padding: 0 8px; border-radius: 99px; font-size: 12px;
	display: inline-flex; align-items: center; background: var(--sg2); color: var(--ig6); }
.acp-chip--blue { background: var(--blue-bg); color: var(--blue-ink); }
.acp-chip--right { margin-left: auto; }
.acp-chip--blue + .acp-chip--right { margin-left: 8px; }

.acp-log { flex: 1; min-height: 0; overflow-y: auto; padding: 14px; display: flex; flex-direction: column;
	gap: 10px; background: var(--sg1); }
/* Transcript items must never flex-shrink: a card whose root has
   overflow:hidden gets an automatic minimum size of ZERO in a flex column,
   so it absorbed all the shrink and rendered 2px tall — buttons present in
   the DOM, invisible on screen (diagnosed live, 2026-08-08). Vue applies
   this scope to child component roots, so cards are covered. */
.acp-log > * { flex-shrink: 0; }
.acp-msg { max-width: 90%; border-radius: 10px; padding: 8px 12px; }
.acp-msg--user { align-self: flex-end; background: var(--sg4); color: var(--ig9); white-space: pre-wrap; }
.acp-msg--agent { align-self: flex-start; background: var(--sw); border: 1px solid var(--og2); }
.acp-msg--agent :deep(p) { margin: 0 0 6px; } .acp-msg--agent :deep(p:last-child) { margin: 0; }
.acp-msg--agent :deep(pre) { background: var(--sg2); border-radius: 8px; padding: 8px; overflow-x: auto; }
.acp-msg--agent :deep(table) { border-collapse: collapse; }
.acp-msg--agent :deep(td), .acp-msg--agent :deep(th) { border: 1px solid var(--og2); padding: 3px 8px; }

.acp-card { align-self: flex-start; width: 94%; background: var(--sw); border: 1px solid var(--og2);
	border-radius: 10px; overflow: hidden; }
.acp-card-head { padding: 8px 12px; border-bottom: 1px solid var(--og1); background: var(--sg1);
	font-weight: 600; color: var(--ig9); font-size: 12px; }
.acp-card-head--muted { color: var(--ig5); font-family: ui-monospace, Menlo, monospace; font-weight: 400; }
.acp-card-opts { display: flex; gap: 8px; flex-wrap: wrap; padding: 10px 12px; }
.acp-fallback { padding: 8px 12px; } .acp-fallback pre { font-size: 11px; overflow-x: auto; }

.acp-thinking { color: var(--ig5); font-style: italic; font-size: 12px; }
.acp-status { font-size: 11px; color: var(--ig5); display: flex; gap: 6px; align-items: center; }
.acp-dot { width: 7px; height: 7px; border-radius: 99px; background: var(--green-ink); }
.acp-dot--err { background: var(--red-ink); }
.acp-starters { display: flex; flex-direction: column; align-items: stretch; gap: 6px;
	margin-top: auto; padding-bottom: 4px; }
/* Starter chips carry full sentences: they must grow with their text
   instead of overflowing the fixed 28px button height into the composer
   (reported 2026-08-08). */
.acp-starters .acp-btn { height: auto; min-height: 28px; white-space: normal; text-align: left;
	justify-content: flex-start; padding: 6px 10px; line-height: 1.4; }

.acp-toolbar { display: flex; gap: 12px; padding: 8px 14px 0; border-top: 1px solid var(--og2); background: var(--sw); }
.acp-tb { border: none; background: none; color: var(--ig5); cursor: pointer; font-size: 12px; padding: 0; }
.acp-composer { display: flex; gap: 8px; padding: 6px 14px 12px; background: var(--sw); }
.acp-input { flex: 1; resize: none; height: 28px; min-height: 28px; max-height: 132px; overflow-y: auto;
	border-radius: 8px; padding: 4px 10px;
	font-size: 14px; font-family: inherit; color: var(--ig8); background: var(--sg2);
	border: 1px solid var(--sg2); }
.acp-input::placeholder { color: var(--ig4); }
.acp-input:focus { outline: none; background: var(--sw); border-color: var(--og2); }

.acp-btn { display: inline-flex; align-items: center; gap: 6px; height: 28px; padding: 0 10px; border: none;
	border-radius: 8px; font-size: 14px; cursor: pointer; background: var(--sg2); color: var(--ig8); }
.acp-btn--solid { background: var(--sg7); color: var(--iw); }
.acp-btn--subtle { background: var(--sg2); color: var(--ig8); }
.acp-btn--outline { background: var(--sw); border: 1px solid var(--og2); }
.acp-btn:disabled { opacity: 0.55; cursor: default; }
.acp-error-text { color: var(--ig8); }
.acp-filechip { display: inline-flex; align-items: center; gap: 4px; margin-left: 8px; font-size: 11.5px;
	background: var(--sg2); border-radius: 6px; padding: 1px 7px; color: var(--ig6); }
.acp-pending-file { display: flex; align-items: center; gap: 6px; padding: 4px 14px 0; background: var(--sw); }
.acp-hidden { display: none; }
</style>
