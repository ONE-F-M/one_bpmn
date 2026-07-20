<template>
	<Teleport to="body">
		<!-- Scrim -->
		<div v-if="modelValue" class="lx-scrim" @click.self="handleClose">
			<!-- Chat window -->
			<div class="lx-window" role="dialog" aria-modal="true" aria-label="Logix AI Assistant">

				<!-- ── Header ─────────────────────────────────────────────── -->
				<div class="lx-header">
					<div class="lx-header-left">
						<span class="lx-logo-icon" aria-hidden="true">
							<svg viewBox="0 0 24 24" fill="none">
								<path d="M13 2L3 14h9l-1 8 10-12h-9l1-8z" fill="currentColor"/>
							</svg>
						</span>
						<span class="lx-title">Logix</span>
						<span v-if="elementLabel" class="lx-context-chip" :title="elementLabel">
							{{ elementLabel }}
						</span>
					</div>
					<div class="lx-header-actions">
						<button class="lx-icon-btn" title="New conversation" @click="resetConversation">
							<svg viewBox="0 0 24 24" fill="currentColor" width="18" height="18">
								<path d="M17.65 6.35A7.958 7.958 0 0 0 12 4c-4.42 0-7.99 3.58-7.99 8s3.57 8 7.99 8c3.73 0 6.84-2.55 7.73-6h-2.08A5.99 5.99 0 0 1 12 18c-3.31 0-6-2.69-6-6s2.69-6 6-6c1.66 0 3.14.69 4.22 1.78L13 11h7V4l-2.35 2.35z"/>
							</svg>
						</button>
						<button class="lx-icon-btn lx-close-btn" title="Close" @click="handleClose">
							<svg viewBox="0 0 24 24" fill="currentColor" width="18" height="18">
								<path d="M19 6.41L17.59 5 12 10.59 6.41 5 5 6.41 10.59 12 5 17.59 6.41 19 12 13.41 17.59 19 19 17.59 13.41 12z"/>
							</svg>
						</button>
					</div>
				</div>

				<!-- ── Messages ───────────────────────────────────────────── -->
				<div class="lx-messages" ref="messagesEl">

					<!-- Welcome state (shown before first message) -->
					<div v-if="messages.length === 0" class="lx-welcome">
						<div class="lx-welcome-title">Hello, I am Logix</div>
						<div class="lx-welcome-sub">Your AI assistant for server scripts</div>
					</div>

					<div
						v-for="msg in messages"
						:key="msg.id"
						:class="['lx-msg-row', msg.role]"
					>
						<!-- Avatar for assistant messages -->
						<div v-if="msg.role === 'assistant'" class="lx-avatar">
							<svg viewBox="0 0 24 24" fill="currentColor">
								<path d="M13 2L3 14h9l-1 8 10-12h-9l1-8z"/>
							</svg>
						</div>

						<div class="lx-msg-body">
							<div :class="msg.role === 'user' ? 'lx-bubble-user' : 'lx-bubble-bot'">
								<!-- Render parsed parts -->
								<template v-for="(part, pi) in parseMessage(msg.content)" :key="pi">
									<div v-if="part.type === 'text'" v-html="renderMarkdown(part.content)" class="lx-text-part"></div>
									<div v-else-if="part.type === 'code'" class="lx-code-block">
										<div class="lx-code-header">
											<span class="lx-code-lang">{{ part.lang || 'python' }}</span>
											<div class="lx-code-actions">
												<button class="lx-copy-btn" @click="copyCode(part.content, `${msg.id}-${pi}`)" title="Copy">
													<svg viewBox="0 0 24 24" fill="currentColor" width="14" height="14">
														<path d="M16 1H4c-1.1 0-2 .9-2 2v14h2V3h12V1zm3 4H8c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h11c1.1 0 2-.9 2-2V7c0-1.1-.9-2-2-2zm0 16H8V7h11v14z"/>
													</svg>
													{{ copiedIndex === `${msg.id}-${pi}` ? 'Copied!' : 'Copy' }}
												</button>
												<button
													v-if="msg.role === 'assistant' && !['CREATE','MODIFY'].includes(msg.intent)"
													class="lx-apply-btn"
													@click="openApplyDialog(part.content)"
												>
													<svg viewBox="0 0 24 24" fill="currentColor" width="14" height="14">
														<path d="M9 16.17L4.83 12l-1.42 1.41L9 19 21 7l-1.41-1.41z"/>
													</svg>
													Apply Script
												</button>
											</div>
										</div>
										<pre class="lx-code-pre"><code>{{ part.content }}</code></pre>
									</div>
								</template>
								<!-- Copy button on assistant messages (shows on hover) -->
								<div v-if="msg.role === 'assistant'" class="lx-message-actions">
									<button class="lx-copy-msg-btn" @click="copyMessage(msg.content)" title="Copy message">
										<svg xmlns="http://www.w3.org/2000/svg" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
											<rect width="14" height="14" x="8" y="8" rx="2" ry="2"/>
											<path d="M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2"/>
										</svg>
									</button>
								</div>
							</div>
							<div class="lx-msg-time" :class="msg.role === 'user' ? 'lx-time-right' : 'lx-time-left'">{{ msg.time }}</div>
						</div>

						<!-- Split diff view for MODIFY intent -->
						<div v-if="msg.diffRows?.length" class="lx-split-diff">
							<div class="lx-split-header">
								<div class="lx-split-col-label">Original</div>
								<div class="lx-split-header-divider"></div>
								<div class="lx-split-col-label">Proposed</div>
							</div>
							<div class="lx-split-body">
								<div v-for="(row, ri) in msg.diffRows" :key="ri" class="lx-split-row">
									<pre :class="['lx-split-cell', splitCellClass(row, 'left')]">{{ row.left ?? '' }}</pre>
									<div class="lx-split-divider"></div>
									<pre :class="['lx-split-cell', splitCellClass(row, 'right')]">{{ row.right ?? '' }}</pre>
								</div>
							</div>
						</div>

						<!-- Inline action buttons -->
						<div v-if="msg.actions?.length" class="lx-msg-actions">
							<button
								v-for="action in msg.actions"
								:key="action.handler + action.label"
								class="lx-action-btn"
								@click="handleMessageAction(action.handler, msg.id, action.value || '')"
							>{{ action.label }}</button>
						</div>
					</div>

					<!-- Typing indicator -->
					<div v-if="isTyping" class="lx-msg-row assistant">
						<div class="lx-avatar">
							<svg viewBox="0 0 24 24" fill="currentColor">
								<path d="M13 2L3 14h9l-1 8 10-12h-9l1-8z"/>
							</svg>
						</div>
						<div class="lx-msg-body">
							<div class="lx-bubble-bot lx-typing-bubble">
								<div class="lx-typing">
									<span></span><span></span><span></span>
								</div>
							</div>
						</div>
					</div>
				</div>

				<!-- ── Input area (Lumina style) ──────────────────────────── -->
				<div class="lx-input-area">
					<div class="lx-toolbar-row">
						<div class="lx-toolbar">
							<button class="lx-toolbar-btn" @mousedown.prevent="execCmd('bold')" title="Bold"><b>B</b></button>
							<button class="lx-toolbar-btn" @mousedown.prevent="execCmd('italic')" title="Italic"><i>I</i></button>
							<button class="lx-toolbar-btn" @mousedown.prevent="execCmd('underline')" title="Underline"><u>U</u></button>
							<button class="lx-toolbar-btn" @mousedown.prevent="insertLink" title="Link">
								<svg viewBox="0 0 24 24" fill="currentColor" width="14" height="14"><path d="M3.9 12c0-1.71 1.39-3.1 3.1-3.1h4V7H7c-2.76 0-5 2.24-5 5s2.24 5 5 5h4v-1.9H7c-1.71 0-3.1-1.39-3.1-3.1zM8 13h8v-2H8v2zm9-6h-4v1.9h4c1.71 0 3.1 1.39 3.1 3.1s-1.39 3.1-3.1 3.1h-4V17h4c2.76 0 5-2.24 5-5s-2.24-5-5-5z"/></svg>
							</button>
							<button class="lx-toolbar-btn" @mousedown.prevent="execCmd('insertUnorderedList')" title="Bulleted list">
								<svg viewBox="0 0 24 24" fill="currentColor" width="14" height="14"><path d="M4 10.5c-.83 0-1.5.67-1.5 1.5s.67 1.5 1.5 1.5 1.5-.67 1.5-1.5-.67-1.5-1.5-1.5zm0-6c-.83 0-1.5.67-1.5 1.5S3.17 7.5 4 7.5 5.5 6.83 5.5 6 4.83 4.5 4 4.5zm0 12c-.83 0-1.5.68-1.5 1.5s.68 1.5 1.5 1.5 1.5-.68 1.5-1.5-.67-1.5-1.5-1.5zM7 19h14v-2H7v2zm0-6h14v-2H7v2zm0-8v2h14V5H7z"/></svg>
							</button>
							<button class="lx-toolbar-btn" @mousedown.prevent="execCmd('insertOrderedList')" title="Numbered list">
								<svg viewBox="0 0 24 24" fill="currentColor" width="14" height="14"><path d="M2 17h2v.5H3v1h1v.5H2v1h3v-4H2v1zm1-9h1V4H2v1h1v3zm-1 3h1.8L2 13.1v.9h3v-1H3.2L5 10.9V10H2v1zm5-6v2h14V5H7zm0 14h14v-2H7v2zm0-6h14v-2H7v2z"/></svg>
							</button>
						</div>
					</div>
					<div class="lx-editor-row">
						<div
							ref="inputEl"
							class="lx-editor"
							contenteditable="true"
							data-placeholder="Describe the script you need… (Enter to send, Shift+Enter for new line)"
							@keydown="handleKeydown"
							@input="onEditorInput"
						></div>
						<button
							class="lx-send-btn"
							@click="sendMessage"
							:disabled="!editorHasContent || isTyping"
							title="Send"
						>
							<svg viewBox="0 0 24 24" fill="currentColor" width="20" height="20">
								<path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z"/>
							</svg>
						</button>
					</div>
				</div>
			</div>
		</div>

		<!-- ── Apply Script dialog ─────────────────────────────────────── -->
		<div v-if="showApplyDialog" class="lx-scrim lx-apply-scrim" @click.self="showApplyDialog = false">
			<div class="lx-apply-window" role="dialog" aria-modal="true">
				<div class="lx-apply-header">
					<span class="lx-apply-title">Apply Script</span>
				</div>
				<div class="lx-apply-body">
					<p class="lx-apply-hint">
						Enter a name for this Server Script. It will be created and linked to the Script Task.
					</p>
					<div class="lx-apply-field">
						<label class="lx-apply-label">Script Name <span class="lx-required">*</span></label>
						<input
							ref="applyNameInput"
							v-model="applyScriptName"
							class="lx-apply-input"
							placeholder="e.g. Validate Employee Shift"
							@keydown.enter="applyScript"
						/>
					</div>
					<div v-if="applyError" class="lx-apply-error">{{ applyError }}</div>
				</div>
				<div class="lx-apply-actions">
					<button class="lx-btn-text" @click="showApplyDialog = false">Cancel</button>
					<button
						class="lx-btn-filled"
						@click="applyScript"
						:disabled="!applyScriptName.trim() || applyLoading"
					>
						<span v-if="applyLoading" class="lx-spinner"></span>
						{{ applyLoading ? 'Creating…' : 'Create & Link' }}
					</button>
				</div>
			</div>
		</div>
	</Teleport>
</template>

<script setup>
import { ref, computed, watch, nextTick, onUnmounted } from "vue";
import DOMPurify from "dompurify";
import { marked } from "marked";
import { frappeRequest } from "frappe-ui";

marked.setOptions({ gfm: true, breaks: true });

const props = defineProps({
	modelValue:    { type: Boolean, default: false },
	element:       { type: Object,  default: null },
	scriptType:    { type: String,  default: "bpmn:script" },
	currentScript: { type: String,  default: "" },
	eventBus:      { type: Object,  default: null },
});

const emit = defineEmits(["update:modelValue"]);

// ── State ─────────────────────────────────────────────────────────────
const messages         = ref([]);
const editorHasContent = ref(false);
const isTyping         = ref(false);
const sessionId        = ref(generateSessionId());
const messagesEl       = ref(null);
const inputEl          = ref(null);

const showApplyDialog = ref(false);
const applyScriptName = ref("");
const applyScriptCode = ref("");
const applyError      = ref("");
const applyLoading    = ref(false);
const applyNameInput  = ref(null);

const copiedIndex        = ref(null);
const pendingScriptName  = ref("");
const localCurrentScript = ref("");
const conversationName   = ref(null);   // persisted Chat Conversation name

// ── Computed helpers ──────────────────────────────────────────────────
const elementLabel = computed(() => {
	if (!props.element) return "";
	const bo = props.element.businessObject;
	return bo?.name || props.element.id || "";
});

// ── Lifecycle ─────────────────────────────────────────────────────────
watch(() => props.modelValue, (open) => {
	if (open) {
		if (messages.value.length === 0) initGreeting();
		nextTick(() => inputEl.value?.focus());
	}
});

watch(
	() => [props.element?.id, props.currentScript],
	([newId], [oldId]) => {
		if (newId && newId !== oldId) {
			sessionId.value        = generateSessionId();
			conversationName.value = null;
			messages.value         = [];
			initGreeting();
		}
	},
);

// ── Helpers ───────────────────────────────────────────────────────────
function generateSessionId() {
	return "logix_" + Date.now() + "_" + Math.random().toString(36).slice(2, 9);
}

function formatTime(d) {
	return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

function makeId() {
	return Date.now() + "_" + Math.random().toString(36).slice(2, 7);
}

function scrollBottom() {
	nextTick(() => {
		if (messagesEl.value)
			messagesEl.value.scrollTop = messagesEl.value.scrollHeight;
	});
}

// ── Editor helpers ────────────────────────────────────────────────────
function onEditorInput() {
	editorHasContent.value = !!(inputEl.value?.innerText?.trim());
}

function getEditorText() {
	return (inputEl.value?.innerText || inputEl.value?.textContent || "").trim();
}

function clearEditor() {
	if (inputEl.value) {
		inputEl.value.innerHTML = "";
		editorHasContent.value = false;
	}
}

function execCmd(cmd) {
	document.execCommand(cmd, false, null);
	inputEl.value?.focus();
}

function insertLink() {
	const url = prompt("Enter URL:");
	if (url) document.execCommand("createLink", false, url);
	inputEl.value?.focus();
}

// ── Markdown rendering ────────────────────────────────────────────────
function renderMarkdown(text) {
	if (!text) return "";
	const html = marked.parse(text);
	return DOMPurify.sanitize(html, {
		ALLOWED_TAGS: ["b","i","u","s","strong","em","strike","del","a","p","br","div","span",
			"ul","ol","li","h1","h2","h3","h4","h5","h6","code","pre","blockquote","hr",
			"table","thead","tbody","tr","th","td"],
		ALLOWED_ATTR: ["href","title","target","rel","src","alt","width","height","class","align"],
		ALLOWED_URI_REGEXP: /^(?:(?:https?|mailto):)/i,
	});
}

// ── Greeting ──────────────────────────────────────────────────────────
async function initGreeting() {
	const label = elementLabel.value;

	if (props.currentScript) {
		messages.value = [{
			id: makeId(), role: "assistant", time: formatTime(new Date()),
			content: `Hello, I am Logix.\nHappy to help with the server scripts\nHow would you like me to assist in redefining the **${props.currentScript}** server script?`,
		}];
		return;
	}

	if (label) {
		try {
			const data = await frappeRequest({
				url: "/api/method/one_bpmn.api.server_script_api.check_server_script_exists",
				params: { script_name: label },
			});
			if (data?.exists) {
				messages.value = [{
					id: makeId(), role: "assistant", time: formatTime(new Date()),
					content: `Hello, I am Logix.\nHappy to help with the server scripts\nI found an existing server script named **${label}**. Would you like to link it to this Script Task instead of creating a new one?`,
					actions: [
						{ label: "Link existing script", handler: "link_existing" },
						{ label: "Create new script",    handler: "create_new"    },
					],
				}];
				return;
			}
		} catch (_) { /* fall through */ }

		messages.value = [{
			id: makeId(), role: "assistant", time: formatTime(new Date()),
			content: `Hello, I am Logix.\nHappy to help with the server scripts\nHow would you like me to assist in defining the **${label}** server script?`,
		}];
		return;
	}

	messages.value = [{
		id: makeId(), role: "assistant", time: formatTime(new Date()),
		content: `Hello, I am Logix.\nHappy to help with the server scripts\nDescribe what you'd like the new server script to do and I'll write it for you.`,
	}];
}

// ── Message actions ───────────────────────────────────────────────────
async function handleMessageAction(handler, msgId, value = "") {
	const label = elementLabel.value;
	const msg   = messages.value.find(m => m.id === msgId);

	if (handler === "link_existing") {
		if (props.eventBus) {
			props.eventBus.fire("spiff.script.update", {
				element: props.element, scriptType: props.scriptType, script: label,
			});
		}
		if (msg) { msg.actions = null; msg.content += `\n\n**${label}** has been linked to this Script Task.`; }
		scrollBottom();
		setTimeout(() => handleClose(), 1200);

	} else if (handler === "create_new") {
		if (msg) msg.actions = null;
		messages.value.push({
			id: makeId(), role: "assistant", time: formatTime(new Date()),
			content: `How would you like me to assist in defining the **${label}** server script?`,
		});
		scrollBottom();
		nextTick(() => inputEl.value?.focus());

	} else if (handler === "clarify") {
		if (msg) msg.actions = null;
		if (inputEl.value) {
			inputEl.value.innerText = value;
			editorHasContent.value = true;
		}
		sendMessage();

	} else if (handler === "approve_create") {
		const name = pendingScriptName.value || label;
		const code = msg?.modified_script || "";
		if (!name || !code) return;
		if (msg) msg.actions = null;

		try {
			const data = await frappeRequest({
				url: "/api/method/one_bpmn.api.server_script_api.create_server_script",
				params: { script_name: name, script_type: "API", script: code },
			});
			const scriptName = data?.name    || name;
			const apiUrl     = data?.api_url || "";

			if (props.eventBus) {
				props.eventBus.fire("spiff.script.update", {
					element: props.element, scriptType: props.scriptType, script: scriptName,
				});
			}
			pendingScriptName.value  = "";
			localCurrentScript.value = scriptName;
			const urlNote = apiUrl ? `\nReachable at \`${apiUrl}\`` : "";
			messages.value.push({
				id: makeId(), role: "assistant", time: formatTime(new Date()),
				content: `Script **${scriptName}** has been created and linked to this task.${urlNote}\n\nYou can now ask me to modify it and I'll show you the changes before saving.`,
			});
			scrollBottom();
			setTimeout(() => handleClose(), 1400);
		} catch (err) {
			if (msg) msg.actions = [{ label: "Approve", handler: "approve_create" }];
			messages.value.push({ id: makeId(), role: "assistant", time: formatTime(new Date()), content: `Failed to create script: ${err.message}` });
			scrollBottom();
		}

	} else if (handler === "approve_modify") {
		const scriptName = props.currentScript;
		const code       = msg?.modified_script || "";
		if (!scriptName || !code) return;
		if (msg) msg.actions = null;

		try {
			await frappeRequest({
				url: "/api/method/one_bpmn.api.server_script_api.update_server_script",
				params: { script_name: scriptName, script: code },
			});
			messages.value.push({
				id: makeId(), role: "assistant", time: formatTime(new Date()),
				content: `**${scriptName}** has been updated successfully.`,
			});
			scrollBottom();
			setTimeout(() => handleClose(), 1400);
		} catch (err) {
			if (msg) msg.actions = [
				{ label: "Approve & Save", handler: "approve_modify" },
				{ label: "Reject",         handler: "reject_modify"  },
			];
			messages.value.push({ id: makeId(), role: "assistant", time: formatTime(new Date()), content: `Failed to update script: ${err.message}` });
			scrollBottom();
		}

	} else if (handler === "reject_modify") {
		if (msg) { msg.actions = null; msg.diffRows = null; }
		messages.value.push({
			id: makeId(), role: "assistant", time: formatTime(new Date()),
			content: "Changes rejected. The existing script remains unchanged. Let me know if you'd like a different approach.",
		});
		scrollBottom();
		nextTick(() => inputEl.value?.focus());
	}
}

// ── Message parsing ───────────────────────────────────────────────────
function parseMessage(content) {
	const parts = [];
	const codeBlockRe = /```(\w*)\n?([\s\S]*?)```/g;
	let last = 0;
	let match;
	while ((match = codeBlockRe.exec(content)) !== null) {
		if (match.index > last)
			parts.push({ type: "text", content: content.slice(last, match.index) });
		parts.push({ type: "code", lang: match[1] || "python", content: match[2].trim() });
		last = match.index + match[0].length;
	}
	if (last < content.length)
		parts.push({ type: "text", content: content.slice(last) });
	return parts;
}

// ── Send / receive ────────────────────────────────────────────────────
function handleKeydown(e) {
	if (e.key === "Enter" && !e.shiftKey) {
		e.preventDefault();
		sendMessage();
	}
}

async function sendMessage() {
	const text = getEditorText();
	if (!text || isTyping.value) return;

	clearEditor();
	messages.value.push({ id: makeId(), role: "user", content: text, time: formatTime(new Date()) });
	scrollBottom();
	isTyping.value = true;

	try {
		const history = messages.value
			.slice(-10)
			.map(m => ({ type: m.role, content: m.content }));

		const result = await frappeRequest({
			url: "/api/method/one_bpmn.api.server_script_api.process_logix_message",
			params: {
				message:           text,
				session_id:        sessionId.value,
				conversation_name: conversationName.value || null,
				chat_history:      JSON.stringify(history),
				element_name:      elementLabel.value || "",
				current_script:    localCurrentScript.value || props.currentScript || "",
			},
		});

		// Capture the conversation name returned by the backend
		if (result?.conversation_name) conversationName.value = result.conversation_name;

		const reply  = result?.response || "Sorry, I couldn't process that.";
		const intent = result?.intent;
		const diff   = result?.diff   || null;
		const options = result?.options || null;

		if (intent === "CREATE" && result?.suggested_name) {
			pendingScriptName.value = result.suggested_name;
		}

		const msg = { id: makeId(), role: "assistant", content: reply, time: formatTime(new Date()), intent };

		if (intent === "DISAMBIGUATE" && options?.length) {
			msg.actions = options.map(o => ({ label: o, handler: "clarify", value: o }));
		} else if (intent === "MODIFY") {
			msg.modified_script = result?.modified_script || extractCode(reply);
			if (diff) msg.diffRows = parseSplitDiff(diff);
			msg.actions = [
				{ label: "Approve & Save", handler: "approve_modify" },
				{ label: "Reject",         handler: "reject_modify"  },
			];
		} else if (intent === "CREATE") {
			msg.modified_script = result?.modified_script || extractCode(reply);
			msg.actions = [{ label: "Approve", handler: "approve_create" }];
		}

		messages.value.push(msg);
	} catch (err) {
		console.error("Logix error:", err);
		messages.value.push({
			id:      makeId(),
			role:    "assistant",
			content: "Sorry, I encountered an error. Please try again.",
			time:    formatTime(new Date()),
		});
	} finally {
		isTyping.value = false;
		scrollBottom();
		nextTick(() => inputEl.value?.focus());
	}
}

// ── Diff helpers ──────────────────────────────────────────────────────
function extractCode(text) {
	const m = (text || "").match(/```python\s*\n([\s\S]*?)```/);
	return m ? m[1].trim() : (text || "").trim();
}

function parseSplitDiff(unifiedDiff) {
	const rows  = [];
	const lines = (unifiedDiff || "").split("\n");
	let i = 0;
	while (i < lines.length && (lines[i].startsWith("---") || lines[i].startsWith("+++"))) i++;
	while (i < lines.length) {
		const line = lines[i];
		if (!line || line.startsWith("\\")) { i++; continue; }
		if (line.startsWith("@@")) {
			rows.push({ type: "hunk", left: line, right: line });
			i++; continue;
		}
		if (line.startsWith("-")) {
			const left = line.slice(1);
			if (i + 1 < lines.length && lines[i + 1].startsWith("+")) {
				rows.push({ type: "changed", left, right: lines[i + 1].slice(1) });
				i += 2;
			} else {
				rows.push({ type: "deleted", left, right: null });
				i++;
			}
		} else if (line.startsWith("+")) {
			rows.push({ type: "added", left: null, right: line.slice(1) });
			i++;
		} else {
			const text = line.startsWith(" ") ? line.slice(1) : line;
			rows.push({ type: "unchanged", left: text, right: text });
			i++;
		}
	}
	return rows;
}

function splitCellClass(row, side) {
	if (row.type === "hunk")      return "lx-sdiff-hunk";
	if (row.type === "unchanged") return "";
	if (row.type === "deleted")   return side === "left"  ? "lx-sdiff-del"  : "lx-sdiff-empty";
	if (row.type === "added")     return side === "right" ? "lx-sdiff-add"  : "lx-sdiff-empty";
	if (row.type === "changed")   return side === "left"  ? "lx-sdiff-del"  : "lx-sdiff-add";
	return "";
}

// ── Copy helpers ──────────────────────────────────────────────────────
async function copyCode(code, index) {
	try {
		await navigator.clipboard.writeText(code);
		copiedIndex.value = index;
		setTimeout(() => { copiedIndex.value = null; }, 2000);
	} catch { /* fallback */ }
}

async function copyMessage(content) {
	try { await navigator.clipboard.writeText(content); } catch { /* fallback */ }
}

// ── Apply script ──────────────────────────────────────────────────────
function openApplyDialog(code) {
	applyScriptCode.value = code;
	applyScriptName.value = pendingScriptName.value || "";
	applyError.value      = "";
	showApplyDialog.value = true;
	nextTick(() => applyNameInput.value?.focus());
}

async function applyScript() {
	const name = applyScriptName.value.trim();
	if (!name) return;

	applyError.value   = "";
	applyLoading.value = true;

	try {
		const data = await frappeRequest({
			url: "/api/method/one_bpmn.api.server_script_api.create_server_script",
			params: { script_name: name, script_type: "API", script: applyScriptCode.value },
		});
		const scriptName = data?.name    || name;
		const apiUrl     = data?.api_url || "";

		if (props.eventBus) {
			props.eventBus.fire("spiff.script.update", {
				element:    props.element,
				scriptType: props.scriptType,
				script:     scriptName,
			});
		}

		pendingScriptName.value = "";
		showApplyDialog.value   = false;

		const urlNote = apiUrl ? `\nReachable at \`${apiUrl}\`` : "";
		messages.value.push({
			id:      makeId(),
			role:    "assistant",
			content: `Script **${scriptName}** has been created and linked to this task.${urlNote}`,
			time:    formatTime(new Date()),
		});
		scrollBottom();
		setTimeout(() => handleClose(), 1400);
	} catch (err) {
		applyError.value = err.message || "Failed to create script. Please try again.";
	} finally {
		applyLoading.value = false;
	}
}

// ── Reset / close ─────────────────────────────────────────────────────
// Close the active Chat Conversation on the backend so its BPMN orchestration
// runs the close branch (Cleanup → Conversation Ended). Fire-and-forget.
function endConversation() {
	const convName = conversationName.value;
	if (!convName) return;
	conversationName.value = null;
	frappeRequest({
		url: "/api/method/one_bpmn.api.server_script_api.end_chat_conversation",
		params: { conversation_name: convName },
	}).catch(() => {});
}

function resetConversation() {
	endConversation();
	sessionId.value          = generateSessionId();
	conversationName.value   = null;
	messages.value           = [];
	localCurrentScript.value = "";
	clearEditor();
	initGreeting();
}

function handleClose() {
	endConversation();
	emit("update:modelValue", false);
}

onUnmounted(() => {
	endConversation();
});
</script>

<style scoped>
/* ── Scrim ──────────────────────────────────────────────────────────── */
.lx-scrim {
	position: fixed;
	inset: 0;
	background: rgba(0, 0, 0, 0.45);
	display: flex;
	align-items: center;
	justify-content: center;
	z-index: 9999;
	backdrop-filter: blur(2px);
}

/* ── Chat window ────────────────────────────────────────────────────── */
.lx-window {
	display: flex;
	flex-direction: column;
	width: min(780px, 92vw);
	height: min(680px, 90vh);
	background: #fff;
	border-radius: 12px;
	box-shadow: 0 8px 32px rgba(0,0,0,.18), 0 2px 8px rgba(0,0,0,.10);
	overflow: hidden;
	font-family: "Google Sans", Roboto, "Segoe UI", system-ui, sans-serif;
}

/* ── Header ─────────────────────────────────────────────────────────── */
.lx-header {
	display: flex;
	align-items: center;
	justify-content: space-between;
	padding: 12px 16px;
	background: linear-gradient(135deg, #6c3fe0 0%, #9b59b6 100%);
	flex-shrink: 0;
}

.lx-header-left {
	display: flex;
	align-items: center;
	gap: 10px;
	min-width: 0;
}

.lx-logo-icon {
	display: flex;
	align-items: center;
	justify-content: center;
	width: 30px;
	height: 30px;
	border-radius: 50%;
	background: rgba(255,255,255,0.2);
	flex-shrink: 0;
	color: #fff;
}

.lx-logo-icon svg {
	width: 16px;
	height: 16px;
}

.lx-title {
	font-size: 16px;
	font-weight: 600;
	color: #fff;
	letter-spacing: .1px;
	flex-shrink: 0;
}

.lx-context-chip {
	background: rgba(255,255,255,0.2);
	border: 1px solid rgba(255,255,255,0.3);
	border-radius: 6px;
	padding: 2px 10px;
	font-size: 12px;
	font-weight: 500;
	color: rgba(255,255,255,0.9);
	max-width: 200px;
	overflow: hidden;
	text-overflow: ellipsis;
	white-space: nowrap;
}

.lx-header-actions {
	display: flex;
	align-items: center;
	gap: 4px;
}

.lx-icon-btn {
	display: flex;
	align-items: center;
	justify-content: center;
	width: 32px;
	height: 32px;
	border: none;
	border-radius: 50%;
	background: rgba(255,255,255,0.15);
	color: #fff;
	cursor: pointer;
	transition: background 0.18s;
	flex-shrink: 0;
}

.lx-icon-btn:hover { background: rgba(255,255,255,0.28); }
.lx-icon-btn svg { display: block; }

/* ── Messages area ──────────────────────────────────────────────────── */
.lx-messages {
	flex: 1;
	overflow-y: auto;
	padding: 24px;
	background: #fff;
	display: flex;
	flex-direction: column;
	gap: 18px;
}

.lx-messages::-webkit-scrollbar { width: 6px; }
.lx-messages::-webkit-scrollbar-track { background: transparent; }
.lx-messages::-webkit-scrollbar-thumb { background: #ddd; border-radius: 3px; }

/* ── Welcome state ──────────────────────────────────────────────────── */
.lx-welcome {
	display: flex;
	flex-direction: column;
	align-items: center;
	justify-content: center;
	flex: 1;
	text-align: center;
	padding-top: 60px;
}

.lx-welcome-title {
	font-size: 1.4em;
	color: #444;
	font-weight: 500;
	margin-bottom: 8px;
}

.lx-welcome-sub {
	font-size: 1em;
	color: #888;
}

/* ── Individual message row ─────────────────────────────────────────── */
.lx-msg-row {
	display: flex;
	flex-direction: row;
	gap: 10px;
	align-items: flex-start;
	width: 100%;
}

.lx-msg-row.user      { flex-direction: row-reverse; }
.lx-msg-row.assistant { /* full width by default */ }

/* ── Avatar ─────────────────────────────────────────────────────────── */
.lx-avatar {
	width: 32px;
	height: 32px;
	border-radius: 50%;
	background: linear-gradient(135deg, #6c3fe0 0%, #9b59b6 100%);
	display: flex;
	align-items: center;
	justify-content: center;
	flex-shrink: 0;
	margin-top: 2px;
	color: #fff;
}

.lx-avatar svg {
	width: 16px;
	height: 16px;
	fill: #fff;
}

.lx-msg-body {
	display: flex;
	flex-direction: column;
	gap: 4px;
	min-width: 0;
}

.lx-msg-row.user .lx-msg-body      { align-items: flex-end; max-width: 75%; }
.lx-msg-row.assistant .lx-msg-body { align-items: flex-start; max-width: calc(100% - 44px); }

/* ── Bubbles (Lumina style) ─────────────────────────────────────────── */
.lx-bubble-user {
	background: linear-gradient(135deg, #6c3fe0 0%, #9b59b6 100%);
	color: #fff;
	padding: 12px 18px;
	border-radius: 18px 18px 4px 18px;
	font-size: 1em;
	box-shadow: 0 2px 8px rgba(108, 63, 224, 0.25);
	overflow-wrap: break-word;
	word-break: break-word;
	position: relative;
}

.lx-bubble-bot {
	background: #f7f7fa;
	color: #000;
	padding: 12px 18px;
	border-radius: 18px 18px 18px 4px;
	font-size: 1em;
	box-shadow: 0 2px 8px rgba(0, 0, 0, 0.04);
	overflow-wrap: break-word;
	word-break: break-word;
	position: relative;
	display: flex;
	flex-direction: column;
}

/* ── Text parts ─────────────────────────────────────────────────────── */
.lx-text-part {
	margin: 0;
	line-height: 1.55;
}

.lx-text-part :deep(p) { margin: 0 0 6px; }
.lx-text-part :deep(p:last-child) { margin-bottom: 0; }
.lx-text-part :deep(ul), .lx-text-part :deep(ol) { margin: 4px 0 4px 1.2em; }
.lx-text-part :deep(code) {
	background: #f0f0f0;
	border-radius: 3px;
	padding: 1px 4px;
	font-family: monospace;
	font-size: 0.9em;
}

/* ── Timestamp ──────────────────────────────────────────────────────── */
.lx-msg-time {
	font-size: 0.82em;
	color: #888;
	margin-top: 3px;
}

.lx-time-right { text-align: right; }
.lx-time-left  { text-align: left; }

/* ── Message copy button (appears on hover) ─────────────────────────── */
.lx-message-actions {
	margin-top: 8px;
	display: flex;
	gap: 8px;
	opacity: 0.5;
	transition: opacity 0.2s;
}

.lx-bubble-bot:hover .lx-message-actions { opacity: 1; }

.lx-copy-msg-btn {
	background: transparent;
	border: none;
	padding: 3px;
	cursor: pointer;
	color: #777;
	display: flex;
	align-items: center;
	border-radius: 4px;
	transition: background 0.18s, color 0.18s;
}

.lx-copy-msg-btn:hover {
	background: rgba(0, 0, 0, 0.08);
	color: #333;
}

/* ── Inline code ────────────────────────────────────────────────────── */
:deep(.lx-inline-code) {
	background: #f0f0f0;
	border-radius: 4px;
	padding: 1px 5px;
	font-family: monospace;
	font-size: 0.9em;
}

/* ── Code block ─────────────────────────────────────────────────────── */
.lx-code-block {
	margin: 8px -4px 4px;
	border-radius: 8px;
	overflow: hidden;
	border: 1px solid #e0e0e0;
}

.lx-code-header {
	display: flex;
	align-items: center;
	justify-content: space-between;
	padding: 6px 12px;
	background: #f5f5f5;
}

.lx-code-lang {
	font-size: 11px;
	font-weight: 600;
	color: #555;
	text-transform: uppercase;
	letter-spacing: .5px;
	font-family: monospace;
}

.lx-code-actions {
	display: flex;
	align-items: center;
	gap: 6px;
}

.lx-copy-btn,
.lx-apply-btn {
	display: flex;
	align-items: center;
	gap: 4px;
	border: none;
	border-radius: 6px;
	padding: 4px 10px;
	font-size: 12px;
	font-weight: 500;
	cursor: pointer;
	transition: background 0.18s;
	font-family: inherit;
}

.lx-copy-btn {
	background: rgba(0,0,0,.06);
	color: #444;
}

.lx-copy-btn:hover { background: rgba(0,0,0,.12); }

.lx-apply-btn {
	background: linear-gradient(135deg, #6c3fe0 0%, #9b59b6 100%);
	color: #fff;
}

.lx-apply-btn:hover { opacity: 0.88; }

.lx-code-pre {
	margin: 0;
	padding: 14px 16px;
	background: #1c1b1f;
	color: #e6e1e5;
	font-family: "JetBrains Mono", "Cascadia Code", "Fira Code", monospace;
	font-size: 13px;
	line-height: 1.6;
	overflow-x: auto;
	white-space: pre;
}

/* ── Typing indicator ───────────────────────────────────────────────── */
.lx-typing-bubble {
	padding: 14px 18px !important;
}

.lx-typing {
	display: flex;
	gap: 5px;
	align-items: center;
}

.lx-typing span {
	display: block;
	width: 7px;
	height: 7px;
	border-radius: 50%;
	background: #aaa;
	animation: lx-bounce 1.4s infinite ease-in-out;
}

.lx-typing span:nth-child(1) { animation-delay: -0.32s; }
.lx-typing span:nth-child(2) { animation-delay: -0.16s; }

@keyframes lx-bounce {
	0%, 80%, 100% { transform: scale(0.75); opacity: 0.5; }
	40%            { transform: scale(1);    opacity: 1;   }
}

/* ── Input area ─────────────────────────────────────────────────────── */
.lx-input-area {
	background: #fff;
	border-top: 1px solid #eee;
	flex-shrink: 0;
	padding: 8px 16px 12px;
}

.lx-toolbar-row {
	margin-bottom: 6px;
}

.lx-toolbar {
	display: flex;
	align-items: center;
	gap: 2px;
}

.lx-toolbar-btn {
	background: transparent;
	border: 1px solid transparent;
	border-radius: 4px;
	padding: 3px 7px;
	font-size: 13px;
	color: #444;
	cursor: pointer;
	line-height: 1;
	display: flex;
	align-items: center;
	justify-content: center;
	min-width: 28px;
	min-height: 26px;
	transition: background 0.15s, border-color 0.15s;
}

.lx-toolbar-btn:hover {
	background: #f0f0f0;
	border-color: #ddd;
}

.lx-editor-row {
	display: flex;
	align-items: flex-start;
	gap: 10px;
	padding-bottom: 4px;
}

.lx-editor {
	flex: 1;
	border: 1px solid #d1d8dd;
	border-radius: 6px;
	padding: 8px 12px;
	font-size: 14px;
	font-family: inherit;
	min-height: 40px;
	max-height: 120px;
	overflow-y: auto;
	outline: none;
	line-height: 1.5;
	color: #1c1b1f;
	background: #fff;
	transition: border-color 0.15s, box-shadow 0.15s;
	word-break: break-word;
}

.lx-editor:focus {
	border-color: #80bdff;
	box-shadow: 0 0 0 0.2rem rgba(0, 123, 255, 0.2);
}

.lx-editor:empty::before {
	content: attr(data-placeholder);
	color: #6c757d;
	pointer-events: none;
	display: block;
}

.lx-send-btn {
	width: 40px;
	height: 40px;
	border-radius: 50%;
	background: linear-gradient(135deg, #6c3fe0 0%, #9b59b6 100%);
	border: none;
	color: #fff;
	display: flex;
	align-items: center;
	justify-content: center;
	cursor: pointer;
	flex-shrink: 0;
	transition: opacity 0.18s, transform 0.12s;
}

.lx-send-btn:hover:not(:disabled) { opacity: 0.88; transform: scale(1.06); }
.lx-send-btn:active:not(:disabled) { opacity: 0.75; transform: scale(.97); }
.lx-send-btn:disabled { background: #ccc; cursor: not-allowed; }

/* ── Apply dialog ───────────────────────────────────────────────────── */
.lx-apply-scrim { z-index: 10000; }

.lx-apply-window {
	background: #fff;
	border-radius: 12px;
	width: min(440px, 90vw);
	overflow: hidden;
	box-shadow: 0 8px 32px rgba(0,0,0,.18);
	font-family: "Google Sans", Roboto, system-ui, sans-serif;
}

.lx-apply-header { padding: 20px 24px 0; }
.lx-apply-title { font-size: 17px; font-weight: 600; color: #1c1b1f; }

.lx-apply-body {
	padding: 14px 24px;
	display: flex;
	flex-direction: column;
	gap: 12px;
}

.lx-apply-hint { margin: 0; font-size: 14px; color: #555; line-height: 1.5; }
.lx-apply-field { display: flex; flex-direction: column; gap: 6px; }
.lx-apply-label { font-size: 12px; font-weight: 600; color: #555; }
.lx-required { color: #c00; }

.lx-apply-input {
	border: 1px solid #ccc;
	border-radius: 6px;
	padding: 8px 12px;
	font-size: 14px;
	font-family: inherit;
	outline: none;
	background: #fff;
	color: #1c1b1f;
	transition: border-color 0.15s;
}

.lx-apply-input:focus {
	border-color: #6c3fe0;
	box-shadow: 0 0 0 2px rgba(108,63,224,.15);
}

.lx-apply-error {
	font-size: 12px;
	color: #c00;
	background: #fff5f5;
	border-radius: 6px;
	padding: 8px 12px;
}

.lx-apply-actions {
	display: flex;
	justify-content: flex-end;
	gap: 8px;
	padding: 10px 24px 18px;
}

.lx-btn-text {
	border: none;
	background: transparent;
	color: #6c3fe0;
	font-size: 14px;
	font-weight: 500;
	font-family: inherit;
	padding: 8px 16px;
	border-radius: 6px;
	cursor: pointer;
	transition: background 0.15s;
}

.lx-btn-text:hover { background: rgba(108,63,224,.08); }

.lx-btn-filled {
	display: flex;
	align-items: center;
	gap: 6px;
	border: none;
	background: linear-gradient(135deg, #6c3fe0 0%, #9b59b6 100%);
	color: #fff;
	font-size: 14px;
	font-weight: 500;
	font-family: inherit;
	padding: 8px 20px;
	border-radius: 6px;
	cursor: pointer;
	transition: opacity 0.15s;
}

.lx-btn-filled:hover:not(:disabled) { opacity: 0.88; }
.lx-btn-filled:disabled { background: #ccc; cursor: not-allowed; }

/* ── Spinner ────────────────────────────────────────────────────────── */
.lx-spinner {
	width: 13px;
	height: 13px;
	border: 2px solid rgba(255,255,255,.4);
	border-top-color: #fff;
	border-radius: 50%;
	animation: lx-spin 0.7s linear infinite;
	display: inline-block;
}

@keyframes lx-spin { to { transform: rotate(360deg); } }

/* ── Inline message action buttons ───────────────────────────────── */
.lx-msg-actions {
	display: flex;
	gap: 8px;
	margin-top: 8px;
	flex-wrap: wrap;
}

.lx-action-btn {
	padding: 5px 14px;
	border-radius: 20px;
	border: 1.5px solid #6c3fe0;
	background: transparent;
	color: #6c3fe0;
	font-size: 13px;
	font-weight: 500;
	cursor: pointer;
	transition: background 0.15s, color 0.15s, border-color 0.15s;
}

.lx-action-btn:hover {
	background: linear-gradient(135deg, #6c3fe0 0%, #9b59b6 100%);
	color: #fff;
	border-color: transparent;
}

/* ── Split diff view (MODIFY intent) ──────────────────────────────── */
.lx-split-diff {
	margin-top: 10px;
	border: 1px solid #e0e0e0;
	border-radius: 8px;
	overflow: hidden;
	width: 100%;
}

.lx-split-header {
	display: grid;
	grid-template-columns: minmax(0, 1fr) 2px minmax(0, 1fr);
	background: #f5f5f5;
	border-bottom: 1px solid #d0d0d0;
}

.lx-split-col-label {
	padding: 6px 12px;
	font-weight: 600;
	font-size: 11px;
	color: #555;
	letter-spacing: 0.05em;
	text-transform: uppercase;
}

.lx-split-header-divider {
	background: #d0d0d0;
	width: 2px;
}

.lx-split-body {
	background: #1c1b1f;
	max-height: 420px;
	overflow-y: auto;
	overflow-x: hidden;
}

.lx-split-row {
	display: grid;
	grid-template-columns: minmax(0, 1fr) 2px minmax(0, 1fr);
	border-bottom: 1px solid rgba(255,255,255,0.04);
	min-height: 22px;
}

.lx-split-divider {
	background: #444;
	width: 2px;
	flex-shrink: 0;
}

.lx-split-cell {
	margin: 0;
	padding: 2px 12px;
	font-family: "JetBrains Mono", "Fira Code", monospace;
	font-size: 12px;
	line-height: 1.6;
	color: #e6e1e5;
	white-space: pre;
	overflow: hidden;
	text-overflow: ellipsis;
	min-width: 0;
}

.lx-sdiff-del   { background: rgba(240,80,80,0.22);   color: #ff9a9a; }
.lx-sdiff-add   { background: rgba(80,200,80,0.18);   color: #7ee89e; }
.lx-sdiff-hunk  { background: rgba(144,202,249,0.10); color: #90caf9; font-style: italic; }
.lx-sdiff-empty { background: rgba(255,255,255,0.02); }
</style>
