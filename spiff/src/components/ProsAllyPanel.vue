<template>
	<div class="flex flex-col h-full pa-root">
		<!-- Header -->
		<div class="pa-header">
			<div class="pa-header-left">
				<span class="pa-logo-icon" aria-hidden="true">
					<svg viewBox="0 0 24 24" fill="none" width="16" height="16">
						<path d="M12 2L2 7l10 5 10-5-10-5z" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
						<path d="M2 17l10 5 10-5" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
						<path d="M2 12l10 5 10-5" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
					</svg>
				</span>
				<span class="pa-title">ProsAlly</span>
			</div>
			<div class="pa-header-actions">
				<button class="pa-icon-btn" title="New conversation" @click="resetConversation">
					<svg viewBox="0 0 24 24" fill="currentColor" width="16" height="16">
						<path d="M17.65 6.35A7.958 7.958 0 0 0 12 4c-4.42 0-7.99 3.58-7.99 8s3.57 8 7.99 8c3.73 0 6.84-2.55 7.73-6h-2.08A5.99 5.99 0 0 1 12 18c-3.31 0-6-2.69-6-6s2.69-6 6-6c1.66 0 3.14.69 4.22 1.78L13 11h7V4l-2.35 2.35z"/>
					</svg>
				</button>
				<button class="pa-icon-btn" title="Close ProsAlly" @click="$emit('close')">
					<svg viewBox="0 0 24 24" fill="currentColor" width="16" height="16">
						<path d="M19 6.41L17.59 5 12 10.59 6.41 5 5 6.41 10.59 12 5 17.59 6.41 19 12 13.41 17.59 19 19 17.59 13.41 12z"/>
					</svg>
				</button>
			</div>
		</div>

		<!-- Messages -->
		<div class="pa-messages" ref="messagesEl">
			<!-- Welcome state (before any messages) -->
			<div v-if="messages.length === 0" class="pa-welcome">
				<div class="pa-welcome-title">Hello, I am ProsAlly</div>
				<div class="pa-welcome-sub">I can help you draw and model your BPMN processes</div>
			</div>

			<div
				v-for="msg in messages"
				:key="msg.id"
				:class="['pa-msg-row', msg.role]"
			>
				<!-- Avatar for assistant messages -->
				<div v-if="msg.role === 'assistant'" class="pa-avatar">
					<svg viewBox="0 0 24 24" fill="none" width="14" height="14">
						<path d="M12 2L2 7l10 5 10-5-10-5z" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
						<path d="M2 17l10 5 10-5" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
						<path d="M2 12l10 5 10-5" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
					</svg>
				</div>

				<div class="pa-msg-body">
					<div :class="msg.role === 'user' ? 'pa-bubble-user' : 'pa-bubble-bot'">
						<div v-html="renderMarkdown(msg.content)" class="pa-text-part"></div>
						<!-- Copy button on assistant messages -->
						<div v-if="msg.role === 'assistant'" class="pa-message-actions">
							<button class="pa-copy-msg-btn" @click="copyMessage(msg.content)" title="Copy message">
								<svg xmlns="http://www.w3.org/2000/svg" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
									<rect width="14" height="14" x="8" y="8" rx="2" ry="2"/>
									<path d="M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2"/>
								</svg>
							</button>
						</div>
						<!-- Option buttons (clarifying or confirmation) -->
						<div v-if="msg.options && msg.options.length" class="pa-options">
							<button
								v-for="opt in msg.options"
								:key="opt"
								:class="[
									'pa-option-btn',
									msg.intent === 'CONFIRM' && opt === 'Yes, proceed'
										? 'pa-option-btn--primary'
										: '',
								]"
								@click="selectOption(opt, msg.id)"
							>{{ opt }}</button>
						</div>
					</div>
					<div class="pa-msg-time" :class="msg.role === 'user' ? 'pa-time-right' : 'pa-time-left'">{{ msg.time }}</div>
				</div>
			</div>

			<!-- Typing indicator -->
			<div v-if="isTyping" class="pa-msg-row assistant">
				<div class="pa-avatar">
					<svg viewBox="0 0 24 24" fill="none" width="14" height="14">
						<path d="M12 2L2 7l10 5 10-5-10-5z" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
						<path d="M2 17l10 5 10-5" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
						<path d="M2 12l10 5 10-5" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
					</svg>
				</div>
				<div class="pa-msg-body">
					<div class="pa-bubble-bot pa-typing-bubble">
						<div class="pa-typing">
							<span></span><span></span><span></span>
						</div>
					</div>
				</div>
			</div>
		</div>

		<!-- Input area (Lumina style) -->
		<div class="pa-input-area">
			<div class="pa-toolbar-row">
				<div class="pa-toolbar">
					<button class="pa-toolbar-btn" @mousedown.prevent="execCmd('bold')" title="Bold"><b>B</b></button>
					<button class="pa-toolbar-btn" @mousedown.prevent="execCmd('italic')" title="Italic"><i>I</i></button>
					<button class="pa-toolbar-btn" @mousedown.prevent="execCmd('underline')" title="Underline"><u>U</u></button>
					<button class="pa-toolbar-btn" @mousedown.prevent="insertLink" title="Link">
						<svg viewBox="0 0 24 24" fill="currentColor" width="13" height="13"><path d="M3.9 12c0-1.71 1.39-3.1 3.1-3.1h4V7H7c-2.76 0-5 2.24-5 5s2.24 5 5 5h4v-1.9H7c-1.71 0-3.1-1.39-3.1-3.1zM8 13h8v-2H8v2zm9-6h-4v1.9h4c1.71 0 3.1 1.39 3.1 3.1s-1.39 3.1-3.1 3.1h-4V17h4c2.76 0 5-2.24 5-5s-2.24-5-5-5z"/></svg>
					</button>
					<button class="pa-toolbar-btn" @mousedown.prevent="execCmd('insertUnorderedList')" title="Bulleted list">
						<svg viewBox="0 0 24 24" fill="currentColor" width="13" height="13"><path d="M4 10.5c-.83 0-1.5.67-1.5 1.5s.67 1.5 1.5 1.5 1.5-.67 1.5-1.5-.67-1.5-1.5-1.5zm0-6c-.83 0-1.5.67-1.5 1.5S3.17 7.5 4 7.5 5.5 6.83 5.5 6 4.83 4.5 4 4.5zm0 12c-.83 0-1.5.68-1.5 1.5s.68 1.5 1.5 1.5 1.5-.68 1.5-1.5-.67-1.5-1.5-1.5zM7 19h14v-2H7v2zm0-6h14v-2H7v2zm0-8v2h14V5H7z"/></svg>
					</button>
					<button class="pa-toolbar-btn" @mousedown.prevent="execCmd('insertOrderedList')" title="Numbered list">
						<svg viewBox="0 0 24 24" fill="currentColor" width="13" height="13"><path d="M2 17h2v.5H3v1h1v.5H2v1h3v-4H2v1zm1-9h1V4H2v1h1v3zm-1 3h1.8L2 13.1v.9h3v-1H3.2L5 10.9V10H2v1zm5-6v2h14V5H7zm0 14h14v-2H7v2zm0-6h14v-2H7v2z"/></svg>
					</button>
				</div>
			</div>
			<div class="pa-editor-row">
				<div
					ref="inputEl"
					class="pa-editor"
					contenteditable="true"
					data-placeholder="Describe the process you want ProsAlly to model…"
					@keydown="handleKeydown"
					@input="onEditorInput"
				></div>
				<button
					class="pa-send-btn"
					@click="sendMessage"
					:disabled="!editorHasContent || isTyping"
					title="Send"
				>
					<svg viewBox="0 0 24 24" fill="currentColor" width="18" height="18">
						<path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z"/>
					</svg>
				</button>
			</div>
		</div>
	</div>
</template>

<script setup>
import { ref, nextTick, onMounted } from "vue";
import DOMPurify from "dompurify";
import { marked } from "marked";

marked.setOptions({ gfm: true, breaks: true });

function getCsrfToken() {
	return (
		window.frappe?.csrf_token ||
		window.frappe?.boot?.csrf_token ||
		window.csrf_token ||
		document.cookie.split("; ").find(r => r.startsWith("csrf_token="))?.split("=")[1] ||
		""
	);
}

const props = defineProps({
	processName:  { type: String,   default: "" },
	diagramName:  { type: String,   default: "" },
	getCanvasXml: { type: Function, default: null },
});

const emit = defineEmits(["close", "bpmn-generated"]);

const messages       = ref([]);
const editorHasContent = ref(false);
const isTyping       = ref(false);
const messagesEl     = ref(null);
const inputEl        = ref(null);
const sessionId      = ref(generateSessionId());

function generateSessionId() {
	return "prosally_" + Date.now() + "_" + Math.random().toString(36).slice(2, 9);
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

async function copyMessage(content) {
	try { await navigator.clipboard.writeText(content); } catch { /* fallback */ }
}

// ── Greeting ──────────────────────────────────────────────────────────
function initGreeting() {
	const processPart = props.processName
		? `How would you like me to assist in defining the **${props.processName}** process on Processa?`
		: "How would you like me to assist in defining your process on Processa?";

	messages.value = [{
		id: makeId(),
		role: "assistant",
		time: formatTime(new Date()),
		content: `Hello, I am ProsAlly.\nI can help to draw your process from scratch, redraw an existing model, or modify a specific part.\n${processPart}`,
	}];
}

onMounted(() => {
	initGreeting();
	nextTick(() => inputEl.value?.focus());
});

function handleKeydown(e) {
	if (e.key === "Enter" && !e.shiftKey) {
		e.preventDefault();
		sendMessage();
	}
}

async function sendMessage(opts = {}) {
	const confirmedAction = opts.confirmedAction || "";
	const text = getEditorText();
	if (!text || isTyping.value) return;

	clearEditor();
	messages.value.push({ id: makeId(), role: "user", content: text, time: formatTime(new Date()) });
	scrollBottom();
	isTyping.value = true;

	try {
		const history = messages.value
			.slice(-10)
			.map(m => ({ role: m.role, content: m.content }));

		const body = {
			message:      text,
			session_id:   sessionId.value,
			chat_history: JSON.stringify(history),
			process_name: props.processName || "",
			diagram_name: props.diagramName || "",
		};
		if (confirmedAction) body.confirmed_action = confirmedAction;
		if (confirmedAction === "MODIFY_EXISTING") {
			if (!props.getCanvasXml) {
				messages.value.push({
					id:      makeId(),
					role:    "assistant",
					content: "I can't modify the existing diagram because the current canvas could not be loaded. Please reload the diagram and try again.",
					time:    formatTime(new Date()),
				});
				return;
			}

			const currentXml = ((await props.getCanvasXml()) || "").trim();
			if (!currentXml) {
				messages.value.push({
					id:      makeId(),
					role:    "assistant",
					content: "I can't modify the existing diagram because the current canvas is empty. Please reload the diagram and try again.",
					time:    formatTime(new Date()),
				});
				return;
			}

			body.current_xml = currentXml;
		}

		const response = await fetch("/api/method/one_bpmn.api.server_script_api.prosally_chat", {
			method: "POST",
			headers: {
				"Content-Type": "application/json",
				"X-Frappe-CSRF-Token": getCsrfToken(),
			},
			body: JSON.stringify(body),
		});

		if (!response.ok) throw new Error(`HTTP ${response.status}`);
		const data   = await response.json();
		const result = data?.message || {};
		const reply  = result.response || "I received your message. How can I assist further?";
		const intent = result.intent || null;
		const options = (result.options && result.options.length) ? result.options : [];

		messages.value.push({
			id:            makeId(),
			role:          "assistant",
			content:       reply,
			intent,
			action_intent: result.action_intent || null,
			options,
			time:          formatTime(new Date()),
		});

		if ((intent === "BPMN_GENERATED" || intent === "BPMN_MODIFIED") && result.bpmn_xml) {
			emit("bpmn-generated", result.bpmn_xml);
		}
	} catch (err) {
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

function selectOption(option, msgId) {
	const msg = messages.value.find(m => m.id === msgId);
	let confirmedAction = "";
	if (msg) {
		if (msg.intent === "CONFIRM" && option === "Yes, proceed") {
			confirmedAction = msg.action_intent || "";
		}
		msg.options = [];
	}

	if (inputEl.value) {
		inputEl.value.innerText = option;
		editorHasContent.value = true;
	}
	sendMessage({ confirmedAction });
}

function resetConversation() {
	sessionId.value = generateSessionId();
	messages.value  = [];
	clearEditor();
	initGreeting();
	nextTick(() => inputEl.value?.focus());
}
</script>

<style scoped>
/* ── Root ───────────────────────────────────────────────────────────── */
.pa-root {
	font-family: "Google Sans", Roboto, "Segoe UI", system-ui, sans-serif;
	background: #fff;
}

/* ── Header ─────────────────────────────────────────────────────────── */
.pa-header {
	display: flex;
	align-items: center;
	justify-content: space-between;
	padding: 10px 14px;
	background: linear-gradient(135deg, #6c3fe0 0%, #9b59b6 100%);
	flex-shrink: 0;
}

.pa-header-left {
	display: flex;
	align-items: center;
	gap: 8px;
	min-width: 0;
}

.pa-logo-icon {
	display: flex;
	align-items: center;
	justify-content: center;
	width: 26px;
	height: 26px;
	border-radius: 50%;
	background: rgba(255,255,255,0.2);
	flex-shrink: 0;
	color: #fff;
}

.pa-title {
	font-size: 14px;
	font-weight: 600;
	color: #fff;
	letter-spacing: 0.1px;
	flex-shrink: 0;
}

.pa-header-actions {
	display: flex;
	align-items: center;
	gap: 2px;
}

.pa-icon-btn {
	display: flex;
	align-items: center;
	justify-content: center;
	width: 28px;
	height: 28px;
	border: none;
	border-radius: 50%;
	background: rgba(255,255,255,0.15);
	color: #fff;
	cursor: pointer;
	transition: background 0.18s;
	flex-shrink: 0;
}

.pa-icon-btn:hover { background: rgba(255,255,255,0.28); }

/* ── Messages ───────────────────────────────────────────────────────── */
.pa-messages {
	flex: 1;
	overflow-y: auto;
	padding: 16px 14px 8px;
	background: #fff;
	display: flex;
	flex-direction: column;
	gap: 14px;
}

.pa-messages::-webkit-scrollbar { width: 4px; }
.pa-messages::-webkit-scrollbar-track { background: transparent; }
.pa-messages::-webkit-scrollbar-thumb { background: #ddd; border-radius: 2px; }

/* ── Welcome state ──────────────────────────────────────────────────── */
.pa-welcome {
	display: flex;
	flex-direction: column;
	align-items: center;
	justify-content: center;
	flex: 1;
	text-align: center;
	padding-top: 40px;
}

.pa-welcome-title {
	font-size: 1.2em;
	color: #444;
	font-weight: 500;
	margin-bottom: 6px;
}

.pa-welcome-sub {
	font-size: 0.9em;
	color: #888;
}

/* ── Message rows ───────────────────────────────────────────────────── */
.pa-msg-row {
	display: flex;
	flex-direction: row;
	gap: 8px;
	align-items: flex-start;
	width: 100%;
}

.pa-msg-row.user      { flex-direction: row-reverse; }
.pa-msg-row.assistant { /* full width by default */ }

/* ── Avatar ─────────────────────────────────────────────────────────── */
.pa-avatar {
	width: 26px;
	height: 26px;
	border-radius: 50%;
	background: linear-gradient(135deg, #6c3fe0 0%, #9b59b6 100%);
	display: flex;
	align-items: center;
	justify-content: center;
	flex-shrink: 0;
	margin-top: 2px;
	color: #fff;
}

.pa-msg-body {
	display: flex;
	flex-direction: column;
	gap: 3px;
	min-width: 0;
}

.pa-msg-row.user .pa-msg-body      { align-items: flex-end; max-width: 80%; }
.pa-msg-row.assistant .pa-msg-body { align-items: flex-start; max-width: calc(100% - 38px); }

/* ── Bubbles (Lumina style) ─────────────────────────────────────────── */
.pa-bubble-user {
	background: linear-gradient(135deg, #6c3fe0 0%, #9b59b6 100%);
	color: #fff;
	padding: 10px 14px;
	border-radius: 18px 18px 4px 18px;
	font-size: 0.92em;
	box-shadow: 0 2px 8px rgba(108, 63, 224, 0.25);
	overflow-wrap: break-word;
	word-break: break-word;
}

.pa-bubble-bot {
	background: #f7f7fa;
	color: #000;
	padding: 10px 14px;
	border-radius: 18px 18px 18px 4px;
	font-size: 0.92em;
	box-shadow: 0 2px 8px rgba(0, 0, 0, 0.04);
	overflow-wrap: break-word;
	word-break: break-word;
	display: flex;
	flex-direction: column;
}

/* ── Text content inside bubbles ────────────────────────────────────── */
.pa-text-part { margin: 0; line-height: 1.55; }
.pa-text-part :deep(p) { margin: 0 0 4px; }
.pa-text-part :deep(p:last-child) { margin-bottom: 0; }
.pa-text-part :deep(ul), .pa-text-part :deep(ol) { margin: 3px 0 3px 1.2em; }
.pa-text-part :deep(code) {
	background: #ebebeb;
	border-radius: 3px;
	padding: 1px 4px;
	font-family: monospace;
	font-size: 0.88em;
}

/* ── Timestamp ──────────────────────────────────────────────────────── */
.pa-msg-time {
	font-size: 0.78em;
	color: #888;
	margin-top: 2px;
}

.pa-time-right { text-align: right; }
.pa-time-left  { text-align: left; }

/* ── Copy button (shows on hover) ───────────────────────────────────── */
.pa-message-actions {
	margin-top: 6px;
	display: flex;
	gap: 6px;
	opacity: 0.5;
	transition: opacity 0.18s;
}

.pa-bubble-bot:hover .pa-message-actions { opacity: 1; }

.pa-copy-msg-btn {
	background: transparent;
	border: none;
	padding: 2px;
	cursor: pointer;
	color: #777;
	display: flex;
	align-items: center;
	border-radius: 4px;
	transition: background 0.15s, color 0.15s;
}

.pa-copy-msg-btn:hover {
	background: rgba(0,0,0,.08);
	color: #333;
}

/* ── Typing indicator ───────────────────────────────────────────────── */
.pa-typing-bubble {
	padding: 12px 16px !important;
}

.pa-typing {
	display: flex;
	gap: 4px;
	align-items: center;
}

.pa-typing span {
	display: block;
	width: 6px;
	height: 6px;
	border-radius: 50%;
	background: #aaa;
	animation: pa-bounce 1.4s infinite ease-in-out;
}

.pa-typing span:nth-child(1) { animation-delay: -0.32s; }
.pa-typing span:nth-child(2) { animation-delay: -0.16s; }

@keyframes pa-bounce {
	0%, 80%, 100% { transform: scale(0.75); opacity: 0.5; }
	40%            { transform: scale(1);    opacity: 1;   }
}

/* ── Input area ─────────────────────────────────────────────────────── */
.pa-input-area {
	background: #fff;
	border-top: 1px solid #eee;
	flex-shrink: 0;
	padding: 6px 12px 10px;
}

.pa-toolbar-row { margin-bottom: 5px; }

.pa-toolbar {
	display: flex;
	align-items: center;
	gap: 2px;
}

.pa-toolbar-btn {
	background: transparent;
	border: 1px solid transparent;
	border-radius: 4px;
	padding: 2px 6px;
	font-size: 12px;
	color: #444;
	cursor: pointer;
	line-height: 1;
	display: flex;
	align-items: center;
	justify-content: center;
	min-width: 24px;
	min-height: 22px;
	transition: background 0.15s, border-color 0.15s;
}

.pa-toolbar-btn:hover {
	background: #f0f0f0;
	border-color: #ddd;
}

.pa-editor-row {
	display: flex;
	align-items: flex-start;
	gap: 8px;
}

.pa-editor {
	flex: 1;
	border: 1px solid #d1d8dd;
	border-radius: 6px;
	padding: 7px 10px;
	font-size: 13px;
	font-family: inherit;
	min-height: 36px;
	max-height: 100px;
	overflow-y: auto;
	outline: none;
	line-height: 1.5;
	color: #1c1b1f;
	background: #fff;
	transition: border-color 0.15s, box-shadow 0.15s;
	word-break: break-word;
}

.pa-editor:focus {
	border-color: #80bdff;
	box-shadow: 0 0 0 0.15rem rgba(0, 123, 255, 0.2);
}

.pa-editor:empty::before {
	content: attr(data-placeholder);
	color: #6c757d;
	pointer-events: none;
	display: block;
}

.pa-send-btn {
	width: 36px;
	height: 36px;
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

.pa-send-btn:hover:not(:disabled) { opacity: 0.88; transform: scale(1.06); }
.pa-send-btn:active:not(:disabled) { opacity: 0.75; transform: scale(0.97); }
.pa-send-btn:disabled { background: #ccc; cursor: not-allowed; }

/* ── Option buttons ─────────────────────────────────────────────────── */
.pa-options {
	display: flex;
	flex-wrap: wrap;
	gap: 5px;
	margin-top: 8px;
}

.pa-option-btn {
	padding: 4px 12px;
	border-radius: 16px;
	border: 1.5px solid #6c3fe0;
	background: transparent;
	color: #6c3fe0;
	font-size: 12px;
	font-weight: 500;
	font-family: inherit;
	cursor: pointer;
	transition: background 0.15s, color 0.15s, border-color 0.15s;
	line-height: 1.4;
}

.pa-option-btn:hover {
	background: linear-gradient(135deg, #6c3fe0 0%, #9b59b6 100%);
	color: #fff;
	border-color: transparent;
}

.pa-option-btn--primary {
	background: linear-gradient(135deg, #6c3fe0 0%, #9b59b6 100%);
	color: #fff;
	border-color: transparent;
}

.pa-option-btn--primary:hover {
	opacity: 0.88;
	border-color: transparent;
}
</style>
