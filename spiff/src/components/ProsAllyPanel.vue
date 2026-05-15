<template>
	<div class="flex flex-col h-full">
		<!-- Header -->
		<div class="pa-header">
			<div class="pa-header-left">
				<span class="pa-logo-icon" aria-hidden="true">
					<svg viewBox="0 0 24 24" fill="none" width="20" height="20">
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
				<button class="pa-icon-btn pa-close-btn" title="Close ProsAlly" @click="$emit('close')">
					<svg viewBox="0 0 24 24" fill="currentColor" width="16" height="16">
						<path d="M19 6.41L17.59 5 12 10.59 6.41 5 5 6.41 10.59 12 5 17.59 6.41 19 12 13.41 17.59 19 19 17.59 13.41 12z"/>
					</svg>
				</button>
			</div>
		</div>

		<!-- Messages -->
		<div class="pa-messages" ref="messagesEl">
			<div
				v-for="msg in messages"
				:key="msg.id"
				:class="['pa-msg', msg.role]"
			>
				<div v-if="msg.role === 'assistant'" class="pa-avatar">
					<svg viewBox="0 0 24 24" fill="none" width="14" height="14">
						<path d="M12 2L2 7l10 5 10-5-10-5z" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
						<path d="M2 17l10 5 10-5" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
						<path d="M2 12l10 5 10-5" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
					</svg>
				</div>
				<div class="pa-msg-body">
					<div class="pa-bubble" v-html="formatText(msg.content)"></div>
					<div class="pa-msg-time">{{ msg.time }}</div>
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
			</div>

			<!-- Typing indicator -->
			<div v-if="isTyping" class="pa-msg assistant">
				<div class="pa-avatar">
					<svg viewBox="0 0 24 24" fill="none" width="14" height="14">
						<path d="M12 2L2 7l10 5 10-5-10-5z" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
						<path d="M2 17l10 5 10-5" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
						<path d="M2 12l10 5 10-5" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
					</svg>
				</div>
				<div class="pa-msg-body">
					<div class="pa-bubble pa-typing-bubble">
						<div class="pa-typing">
							<span></span><span></span><span></span>
						</div>
					</div>
				</div>
			</div>
		</div>

		<!-- Input -->
		<div class="pa-input-row">
			<textarea
				ref="inputEl"
				v-model="inputText"
				@keydown="handleKeydown"
				placeholder="Describe the process you want ProsAlly to model…"
				class="pa-textarea"
				:class="{ 'pa-textarea--disabled': isTyping }"
				:disabled="isTyping"
				rows="2"
			></textarea>
			<button
				class="pa-send-btn"
				@click="sendMessage"
				:disabled="!inputText.trim() || isTyping"
				title="Send"
			>
				<svg viewBox="0 0 24 24" fill="currentColor" width="18" height="18">
					<path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z"/>
				</svg>
			</button>
		</div>
	</div>
</template>

<script setup>
import { ref, nextTick, onMounted } from "vue";

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

const messages    = ref([]);
const inputText   = ref("");
const isTyping    = ref(false);
const messagesEl  = ref(null);
const inputEl     = ref(null);
const sessionId   = ref(generateSessionId());

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

function formatText(text) {
	return (text || "")
		.replace(/&/g, "&amp;")
		.replace(/</g, "&lt;")
		.replace(/>/g, "&gt;")
		.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
		.replace(/\*(.+?)\*/g, "<em>$1</em>")
		.replace(/`([^`]+)`/g, '<code class="pa-inline-code">$1</code>')
		.replace(/\n/g, "<br>");
}

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
	const text = inputText.value.trim();
	if (!text || isTyping.value) return;

	inputText.value = "";
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
		if (confirmedAction === "MODIFY_EXISTING" && props.getCanvasXml) {
			body.current_xml = (await props.getCanvasXml()) || "";
		}

		const response = await fetch("/api/method/one_bpmn.api.prosally_chat", {
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
			id:           makeId(),
			role:         "assistant",
			content:      reply,
			intent,
			action_intent: result.action_intent || null,
			options,
			time:         formatTime(new Date()),
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

	inputText.value = option;
	sendMessage({ confirmedAction });
}

function resetConversation() {
	sessionId.value = generateSessionId();
	messages.value  = [];
	initGreeting();
	nextTick(() => inputEl.value?.focus());
}
</script>

<style scoped>
/* ── Header ─────────────────────────────────────────────────────────── */
.pa-header {
	display: flex;
	align-items: center;
	justify-content: space-between;
	padding: 12px 16px;
	background: #6750a4;
	color: #fff;
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
	width: 28px;
	height: 28px;
	border-radius: 50%;
	background: rgba(255, 255, 255, 0.2);
	flex-shrink: 0;
	color: #fff;
}

.pa-title {
	font-size: 15px;
	font-weight: 600;
	letter-spacing: 0.2px;
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
	width: 30px;
	height: 30px;
	border: none;
	border-radius: 50%;
	background: transparent;
	color: #fff;
	cursor: pointer;
	transition: background 0.2s;
	flex-shrink: 0;
}

.pa-icon-btn:hover {
	background: rgba(255, 255, 255, 0.15);
}

/* ── Messages ───────────────────────────────────────────────────────── */
.pa-messages {
	flex: 1;
	overflow-y: auto;
	padding: 16px 14px 8px;
	background: #f3edf7;
	display: flex;
	flex-direction: column;
	gap: 10px;
}

.pa-messages::-webkit-scrollbar { width: 4px; }
.pa-messages::-webkit-scrollbar-track { background: transparent; }
.pa-messages::-webkit-scrollbar-thumb { background: #cac4d0; border-radius: 2px; }

/* ── Message ────────────────────────────────────────────────────────── */
.pa-msg {
	display: flex;
	gap: 8px;
	max-width: 92%;
}

.pa-msg.user {
	align-self: flex-end;
	flex-direction: row-reverse;
}

.pa-msg.assistant {
	align-self: flex-start;
}

.pa-avatar {
	width: 26px;
	height: 26px;
	border-radius: 50%;
	background: #6750a4;
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
	gap: 2px;
	min-width: 0;
}

.pa-bubble {
	padding: 10px 14px;
	border-radius: 16px;
	font-size: 13px;
	line-height: 1.55;
	word-break: break-word;
}

.pa-msg.user .pa-bubble {
	background: #6750a4;
	color: #fff;
	border-bottom-right-radius: 4px;
}

.pa-msg.assistant .pa-bubble {
	background: #fffbfe;
	color: #1c1b1f;
	border: 1px solid #e6e1e5;
	border-bottom-left-radius: 4px;
}

.pa-msg-time {
	font-size: 10px;
	color: #79747e;
	padding: 0 3px;
}

.pa-msg.user .pa-msg-time { text-align: right; }

/* ── Inline code ────────────────────────────────────────────────────── */
:deep(.pa-inline-code) {
	background: #ece6f0;
	border-radius: 4px;
	padding: 1px 4px;
	font-family: "JetBrains Mono", monospace;
	font-size: 11px;
	color: #21005d;
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
	background: #6750a4;
	animation: pa-bounce 1.4s infinite ease-in-out;
}

.pa-typing span:nth-child(1) { animation-delay: -0.32s; }
.pa-typing span:nth-child(2) { animation-delay: -0.16s; }

@keyframes pa-bounce {
	0%, 80%, 100% { transform: scale(0.75); opacity: 0.5; }
	40%            { transform: scale(1);    opacity: 1;   }
}

/* ── Input ──────────────────────────────────────────────────────────── */
.pa-input-row {
	display: flex;
	align-items: flex-end;
	gap: 8px;
	padding: 10px 12px;
	background: #fffbfe;
	border-top: 1px solid #e6e1e5;
	flex-shrink: 0;
}

.pa-textarea {
	flex: 1;
	border: 1.5px solid #79747e;
	border-radius: 10px;
	padding: 8px 12px;
	font-size: 13px;
	font-family: inherit;
	resize: none;
	outline: none;
	max-height: 80px;
	min-height: 38px;
	line-height: 1.5;
	background: #fffbfe;
	color: #1c1b1f;
	transition: border-color 0.2s;
}

.pa-textarea:focus {
	border-color: #6750a4;
	box-shadow: 0 0 0 2px rgba(103, 80, 164, 0.15);
}

.pa-textarea::placeholder { color: #aca9b4; }

.pa-textarea--disabled {
	opacity: 0.5;
	cursor: not-allowed;
}

.pa-send-btn {
	width: 40px;
	height: 40px;
	border-radius: 12px;
	background: #6750a4;
	border: none;
	color: #fff;
	display: flex;
	align-items: center;
	justify-content: center;
	cursor: pointer;
	flex-shrink: 0;
	transition: background 0.2s, transform 0.15s;
}

.pa-send-btn:hover:not(:disabled) { background: #7965af; transform: scale(1.05); }
.pa-send-btn:active:not(:disabled) { background: #5b4398; transform: scale(0.97); }
.pa-send-btn:disabled { background: #cac4d0; cursor: not-allowed; }

/* ── Clarifying option buttons ──────────────────────────────────────── */
.pa-options {
	display: flex;
	flex-wrap: wrap;
	gap: 6px;
	margin-top: 8px;
}

.pa-option-btn {
	padding: 5px 14px;
	border-radius: 20px;
	border: 1.5px solid #6750a4;
	background: transparent;
	color: #6750a4;
	font-size: 12px;
	font-weight: 500;
	font-family: inherit;
	cursor: pointer;
	transition: background 0.15s, color 0.15s;
	line-height: 1.4;
}

.pa-option-btn:hover {
	background: #6750a4;
	color: #fff;
}

.pa-option-btn--primary {
	background: #6750a4;
	color: #fff;
	border-color: #6750a4;
}

.pa-option-btn--primary:hover {
	background: #7965af;
	border-color: #7965af;
}
</style>
