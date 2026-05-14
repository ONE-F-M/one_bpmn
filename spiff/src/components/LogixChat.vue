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
					<div
						v-for="msg in messages"
						:key="msg.id"
						:class="['lx-msg', msg.role]"
					>
						<!-- Avatar for assistant -->
						<div v-if="msg.role === 'assistant'" class="lx-avatar">
							<svg viewBox="0 0 24 24" fill="currentColor">
								<path d="M13 2L3 14h9l-1 8 10-12h-9l1-8z"/>
							</svg>
						</div>

						<div class="lx-msg-body">
							<div class="lx-bubble">
								<!-- Render each parsed part -->
								<template v-for="(part, pi) in parseMessage(msg.content)" :key="pi">
									<p v-if="part.type === 'text'" v-html="formatText(part.content)" class="lx-text-part"></p>
									<div v-else-if="part.type === 'code'" class="lx-code-block">
										<div class="lx-code-header">
											<span class="lx-code-lang">{{ part.lang || 'python' }}</span>
											<div class="lx-code-actions">
												<button class="lx-copy-btn" @click="copyCode(part.content)" title="Copy">
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
							</div>
							<div class="lx-msg-time">{{ msg.time }}</div>
						</div>
						<!-- Split diff view for MODIFY intent -->
						<div v-if="msg.diffRows?.length" class="lx-split-diff">
							<div class="lx-split-header">
								<div class="lx-split-col-label">Original</div>
								<div class="lx-split-col-label">Proposed</div>
							</div>
							<div class="lx-split-body">
								<div v-for="(row, ri) in msg.diffRows" :key="ri" class="lx-split-row">
									<pre :class="['lx-split-cell', splitCellClass(row, 'left')]">{{ row.left ?? '' }}</pre>
									<pre :class="['lx-split-cell', splitCellClass(row, 'right')]">{{ row.right ?? '' }}</pre>
								</div>
							</div>
						</div>
						<!-- Inline action buttons (link / create-new / clarify / approve / reject) -->
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
					<div v-if="isTyping" class="lx-msg assistant">
						<div class="lx-avatar">
							<svg viewBox="0 0 24 24" fill="currentColor">
								<path d="M13 2L3 14h9l-1 8 10-12h-9l1-8z"/>
							</svg>
						</div>
						<div class="lx-msg-body">
							<div class="lx-bubble lx-typing-bubble">
								<div class="lx-typing">
									<span></span><span></span><span></span>
								</div>
							</div>
						</div>
					</div>
				</div>

				<!-- ── Context bar ────────────────────────────────────────── -->
				<div class="lx-vars-bar">
					<span class="lx-vars-label">Context vars:</span>
					<span v-for="v in contextVars" :key="v" class="lx-var-chip">{{ v }}</span>
				</div>

				<!-- ── Input ──────────────────────────────────────────────── -->
				<div class="lx-input-row">
					<textarea
						ref="inputEl"
						v-model="inputText"
						@keydown="handleKeydown"
						placeholder="Describe the script you need… (Enter to send, Shift+Enter for new line)"
						class="lx-textarea"
						rows="2"
					></textarea>
					<button
						class="lx-send-btn"
						@click="sendMessage"
						:disabled="!inputText.trim() || isTyping"
						title="Send"
					>
						<svg viewBox="0 0 24 24" fill="currentColor" width="20" height="20">
							<path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z"/>
						</svg>
					</button>
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
import { ref, computed, watch, nextTick } from "vue";

const props = defineProps({
	modelValue:    { type: Boolean, default: false },
	element:       { type: Object,  default: null },
	scriptType:    { type: String,  default: "bpmn:script" },
	currentScript: { type: String,  default: "" },
	eventBus:      { type: Object,  default: null },
});

const emit = defineEmits(["update:modelValue"]);

// ── State ─────────────────────────────────────────────────────────────
const messages      = ref([]);
const inputText     = ref("");
const isTyping      = ref(false);
const sessionId     = ref(generateSessionId());
const messagesEl    = ref(null);
const inputEl       = ref(null);

const showApplyDialog = ref(false);
const applyScriptName = ref("");
const applyScriptCode = ref("");
const applyError      = ref("");
const applyLoading    = ref(false);
const applyNameInput  = ref(null);

const copiedIndex      = ref(null);
const pendingScriptName = ref("");

// ── Computed helpers ──────────────────────────────────────────────────
const contextVars = ["frappe.form_dict", "frappe.response[\"message\"]", "frappe.db", "frappe.get_doc"];

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

// Reset conversation whenever the user switches to a different Script Task
watch(
	() => [props.element?.id, props.currentScript],
	([newId], [oldId]) => {
		if (newId && newId !== oldId) {
			sessionId.value = generateSessionId();
			messages.value  = [];
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

async function initGreeting() {
	const label = elementLabel.value;

	// Case 1: Script already linked to this task
	if (props.currentScript) {
		messages.value = [{
			id: makeId(), role: "assistant", time: formatTime(new Date()),
			content: `Hello, I am Logix.\nHappy to help with the server scripts\nHow would you like me to assist in redefining the **${props.currentScript}** server script?`,
		}];
		return;
	}

	// Case 2: No script linked — check if one with the same name as the task already exists
	if (label) {
		try {
			const resp = await fetch(
				`/api/method/one_bpmn.api.check_server_script_exists?script_name=${encodeURIComponent(label)}`,
				{ headers: { "X-Frappe-CSRF-Token": window.frappe?.csrf_token || "" } },
			);
			if (resp.ok) {
				const data = await resp.json();
				if (data?.message?.exists) {
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
			}
		} catch (_) { /* fall through to default */ }

		// No matching script found — offer to define a new one
		messages.value = [{
			id: makeId(), role: "assistant", time: formatTime(new Date()),
			content: `Hello, I am Logix.\nHappy to help with the server scripts\nHow would you like me to assist in defining the **${label}** server script?`,
		}];
		return;
	}

	// Case 3: No script, no label (rare edge case)
	messages.value = [{
		id: makeId(), role: "assistant", time: formatTime(new Date()),
		content: `Hello, I am Logix.\nHappy to help with the server scripts\nDescribe what you'd like the new server script to do and I'll write it for you.`,
	}];
}

async function handleMessageAction(handler, msgId, value = "") {
	const label = elementLabel.value;
	const msg   = messages.value.find(m => m.id === msgId);

	// ── Greeting-level actions ────────────────────────────────────────
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
		inputText.value = value;
		sendMessage();

	// ── CREATE intent ─────────────────────────────────────────────────
	} else if (handler === "approve_create") {
		const name = pendingScriptName.value || label;
		const code = msg?.modified_script || "";
		if (!name || !code) return;
		if (msg) msg.actions = null;

		try {
			const res = await fetch("/api/method/one_bpmn.api.create_server_script", {
				method: "POST",
				headers: { "Content-Type": "application/json", "X-Frappe-CSRF-Token": window.frappe?.csrf_token || "" },
				body: JSON.stringify({ script_name: name, script_type: "API", script: code }),
			});
			if (!res.ok) throw new Error(`HTTP ${res.status}`);
			const data       = await res.json();
			const scriptName = data?.message?.name    || name;
			const apiUrl     = data?.message?.api_url || "";

			if (props.eventBus) {
				props.eventBus.fire("spiff.script.update", {
					element: props.element, scriptType: props.scriptType, script: scriptName,
				});
			}
			pendingScriptName.value = "";
			const urlNote = apiUrl ? `\nReachable at \`${apiUrl}\`` : "";
			messages.value.push({
				id: makeId(), role: "assistant", time: formatTime(new Date()),
				content: `Script **${scriptName}** has been created and linked to this task.${urlNote}`,
			});
			scrollBottom();
			setTimeout(() => handleClose(), 1400);
		} catch (err) {
			if (msg) msg.actions = [{ label: "Approve", handler: "approve_create" }];
			messages.value.push({ id: makeId(), role: "assistant", time: formatTime(new Date()), content: `Failed to create script: ${err.message}` });
			scrollBottom();
		}

	// ── MODIFY intent ─────────────────────────────────────────────────
	} else if (handler === "approve_modify") {
		const scriptName = props.currentScript;
		const code       = msg?.modified_script || "";
		if (!scriptName || !code) return;
		if (msg) msg.actions = null;

		try {
			const res = await fetch("/api/method/one_bpmn.api.update_server_script", {
				method: "POST",
				headers: { "Content-Type": "application/json", "X-Frappe-CSRF-Token": window.frappe?.csrf_token || "" },
				body: JSON.stringify({ script_name: scriptName, script: code }),
			});
			if (!res.ok) throw new Error(`HTTP ${res.status}`);
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

function formatText(text) {
	return text
		.replace(/&/g,  "&amp;")
		.replace(/</g,  "&lt;")
		.replace(/>/g,  "&gt;")
		.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
		.replace(/\*(.+?)\*/g,     "<em>$1</em>")
		.replace(/`([^`]+)`/g,     "<code class=\"lx-inline-code\">$1</code>")
		.replace(/\n/g, "<br>");
}

// ── Send / receive ────────────────────────────────────────────────────
function handleKeydown(e) {
	if (e.key === "Enter" && !e.shiftKey) {
		e.preventDefault();
		sendMessage();
	}
}

async function sendMessage() {
	const text = inputText.value.trim();
	if (!text || isTyping.value) return;

	inputText.value = "";
	messages.value.push({ id: makeId(), role: "user", content: text, time: formatTime(new Date()) });
	scrollBottom();
	isTyping.value = true;

	try {
		const history = messages.value
			.slice(-10)
			.map(m => ({ type: m.role, content: m.content }));

		const response = await fetch("/api/method/one_bpmn.api.process_logix_message", {
			method:  "POST",
			headers: {
				"Content-Type":       "application/json",
				"X-Frappe-CSRF-Token": (window.frappe?.csrf_token) || "",
			},
			body: JSON.stringify({
				message:        text,
				session_id:     sessionId.value,
				chat_history:   JSON.stringify(history),
				element_name:   elementLabel.value || "",
				current_script: props.currentScript || "",
			}),
		});

		if (!response.ok) throw new Error(`HTTP ${response.status}`);
		const data       = await response.json();
		const result     = data?.message;                                          // {intent, response, diff, options, suggested_name}
		const reply      = result?.response || result?.message || "Sorry, I couldn't process that.";
		const intent     = result?.intent;
		const diff       = result?.diff   || null;
		const options    = result?.options || null;

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
	// skip file headers
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
	if (row.type === "deleted")   return side === "left"  ? "lx-sdiff-del"   : "lx-sdiff-empty";
	if (row.type === "added")     return side === "right" ? "lx-sdiff-add"   : "lx-sdiff-empty";
	if (row.type === "changed")   return side === "left"  ? "lx-sdiff-del"   : "lx-sdiff-add";
	return "";
}

// ── Copy code ─────────────────────────────────────────────────────────
async function copyCode(code) {
	try {
		await navigator.clipboard.writeText(code);
	} catch {
		/* fallback */
	}
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
		const res = await fetch("/api/method/one_bpmn.api.create_server_script", {
			method:  "POST",
			headers: {
				"Content-Type":       "application/json",
				"X-Frappe-CSRF-Token": (window.frappe?.csrf_token) || "",
			},
			body: JSON.stringify({
				script_name:  name,
				script_type:  "API",
				script:       applyScriptCode.value,
			}),
		});

		if (!res.ok) {
			const errData = await res.json().catch(() => ({}));
			throw new Error(errData?.exc_type || errData?.message || `HTTP ${res.status}`);
		}

		const data       = await res.json();
		const scriptName = data?.message?.name     || name;
		const apiUrl     = data?.message?.api_url  || "";

		// Fire back to BPMN editor
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

		// Close chat after a short delay
		setTimeout(() => handleClose(), 1400);
	} catch (err) {
		applyError.value = err.message || "Failed to create script. Please try again.";
	} finally {
		applyLoading.value = false;
	}
}

// ── Reset / close ─────────────────────────────────────────────────────
function resetConversation() {
	sessionId.value = generateSessionId();
	messages.value  = [];
	initGreeting();
}

function handleClose() {
	emit("update:modelValue", false);
}
</script>

<style scoped>
/* ── MD3 design tokens ──────────────────────────────────────────────── */
.lx-scrim {
	position: fixed;
	inset: 0;
	background: rgba(0, 0, 0, 0.50);
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
	background: #fffbfe;
	border-radius: 28px;
	box-shadow: 0 4px 8px 3px rgba(0,0,0,.15), 0 1px 3px rgba(0,0,0,.30);
	overflow: hidden;
	font-family: "Google Sans", Roboto, "Segoe UI", system-ui, sans-serif;
}

/* ── Header ─────────────────────────────────────────────────────────── */
.lx-header {
	display: flex;
	align-items: center;
	justify-content: space-between;
	padding: 14px 20px;
	background: #6750a4;
	color: #fff;
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
	width: 32px;
	height: 32px;
	border-radius: 50%;
	background: rgba(255,255,255,.20);
	flex-shrink: 0;
}

.lx-logo-icon svg {
	width: 18px;
	height: 18px;
	fill: #fff;
}

.lx-title {
	font-size: 18px;
	font-weight: 600;
	letter-spacing: .25px;
	flex-shrink: 0;
}

.lx-context-chip {
	background: rgba(255,255,255,.18);
	border: 1px solid rgba(255,255,255,.30);
	border-radius: 8px;
	padding: 2px 10px;
	font-size: 12px;
	font-weight: 500;
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
	width: 36px;
	height: 36px;
	border: none;
	border-radius: 50%;
	background: transparent;
	color: #fff;
	cursor: pointer;
	transition: background 0.2s;
	flex-shrink: 0;
}

.lx-icon-btn:hover {
	background: rgba(255,255,255,.12);
}

.lx-icon-btn svg { display: block; }

/* ── Messages area ──────────────────────────────────────────────────── */
.lx-messages {
	flex: 1;
	overflow-y: auto;
	padding: 20px 20px 8px;
	background: #f3edf7;
	display: flex;
	flex-direction: column;
	gap: 12px;
}

.lx-messages::-webkit-scrollbar { width: 6px; }
.lx-messages::-webkit-scrollbar-track { background: transparent; }
.lx-messages::-webkit-scrollbar-thumb { background: #cac4d0; border-radius: 3px; }

/* ── Individual message ─────────────────────────────────────────────── */
.lx-msg {
	display: flex;
	gap: 10px;
	max-width: 88%;
}

.lx-msg.user {
	align-self: flex-end;
	flex-direction: row-reverse;
}

.lx-msg.assistant {
	align-self: flex-start;
}

.lx-avatar {
	width: 32px;
	height: 32px;
	border-radius: 50%;
	background: #6750a4;
	display: flex;
	align-items: center;
	justify-content: center;
	flex-shrink: 0;
	margin-top: 2px;
}

.lx-avatar svg {
	width: 16px;
	height: 16px;
	fill: #fff;
}

.lx-msg-body {
	display: flex;
	flex-direction: column;
	gap: 3px;
	min-width: 0;
}

.lx-bubble {
	padding: 12px 16px;
	border-radius: 18px;
	font-size: 14px;
	line-height: 1.55;
	word-break: break-word;
}

.lx-msg.user .lx-bubble {
	background: #6750a4;
	color: #fff;
	border-bottom-right-radius: 4px;
}

.lx-msg.assistant .lx-bubble {
	background: #fffbfe;
	color: #1c1b1f;
	border: 1px solid #e6e1e5;
	border-bottom-left-radius: 4px;
}

.lx-msg-time {
	font-size: 11px;
	color: #79747e;
	padding: 0 4px;
}

.lx-msg.user .lx-msg-time { text-align: right; }

/* ── Text parts ─────────────────────────────────────────────────────── */
.lx-text-part {
	margin: 0;
	white-space: pre-wrap;
}

.lx-text-part + .lx-text-part { margin-top: 6px; }

/* ── Inline code ────────────────────────────────────────────────────── */
:deep(.lx-inline-code) {
	background: #ece6f0;
	border-radius: 4px;
	padding: 1px 5px;
	font-family: "JetBrains Mono", "Cascadia Code", monospace;
	font-size: 12px;
	color: #21005d;
}

/* ── Code block ─────────────────────────────────────────────────────── */
.lx-code-block {
	margin: 8px -4px 4px;
	border-radius: 12px;
	overflow: hidden;
	border: 1px solid #e6e1e5;
}

.lx-code-header {
	display: flex;
	align-items: center;
	justify-content: space-between;
	padding: 6px 12px;
	background: #ece6f0;
}

.lx-code-lang {
	font-size: 11px;
	font-weight: 600;
	color: #49454f;
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
	border-radius: 8px;
	padding: 4px 10px;
	font-size: 12px;
	font-weight: 500;
	cursor: pointer;
	transition: background 0.2s, opacity 0.2s;
	font-family: inherit;
}

.lx-copy-btn {
	background: rgba(103,80,164,.08);
	color: #6750a4;
}

.lx-copy-btn:hover { background: rgba(103,80,164,.16); }

.lx-apply-btn {
	background: #6750a4;
	color: #fff;
}

.lx-apply-btn:hover { background: #7965af; }
.lx-apply-btn:active { background: #5b4398; }

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
	background: #6750a4;
	animation: lx-bounce 1.4s infinite ease-in-out;
}

.lx-typing span:nth-child(1) { animation-delay: -0.32s; }
.lx-typing span:nth-child(2) { animation-delay: -0.16s; }

@keyframes lx-bounce {
	0%, 80%, 100% { transform: scale(0.75); opacity: 0.5; }
	40%            { transform: scale(1);    opacity: 1;   }
}

/* ── Context vars bar ───────────────────────────────────────────────── */
.lx-vars-bar {
	display: flex;
	align-items: center;
	flex-wrap: wrap;
	gap: 6px;
	padding: 8px 20px;
	background: #fffbfe;
	border-top: 1px solid #e6e1e5;
	flex-shrink: 0;
}

.lx-vars-label {
	font-size: 11px;
	font-weight: 600;
	color: #79747e;
	text-transform: uppercase;
	letter-spacing: .5px;
}

.lx-var-chip {
	background: #eaddff;
	color: #21005d;
	border-radius: 8px;
	padding: 2px 9px;
	font-size: 11.5px;
	font-weight: 500;
	font-family: "JetBrains Mono", monospace;
}

/* ── Input area ─────────────────────────────────────────────────────── */
.lx-input-row {
	display: flex;
	align-items: flex-end;
	gap: 10px;
	padding: 12px 16px;
	background: #fffbfe;
	border-top: 1px solid #e6e1e5;
	flex-shrink: 0;
}

.lx-textarea {
	flex: 1;
	border: 1.5px solid #79747e;
	border-radius: 12px;
	padding: 10px 14px;
	font-size: 14px;
	font-family: inherit;
	resize: none;
	outline: none;
	max-height: 96px;
	min-height: 44px;
	line-height: 1.5;
	background: #fffbfe;
	color: #1c1b1f;
	transition: border-color 0.2s;
}

.lx-textarea:focus {
	border-color: #6750a4;
	box-shadow: 0 0 0 2px rgba(103,80,164,.15);
}

.lx-textarea::placeholder { color: #aca9b4; }

.lx-send-btn {
	width: 48px;
	height: 48px;
	border-radius: 16px;
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

.lx-send-btn:hover:not(:disabled) { background: #7965af; transform: scale(1.05); }
.lx-send-btn:active:not(:disabled) { background: #5b4398; transform: scale(.97); }
.lx-send-btn:disabled { background: #cac4d0; cursor: not-allowed; }

/* ── Apply dialog ───────────────────────────────────────────────────── */
.lx-apply-scrim { z-index: 10000; }

.lx-apply-window {
	background: #fffbfe;
	border-radius: 28px;
	width: min(440px, 90vw);
	overflow: hidden;
	box-shadow: 0 4px 8px 3px rgba(0,0,0,.15), 0 1px 3px rgba(0,0,0,.30);
	font-family: "Google Sans", Roboto, system-ui, sans-serif;
}

.lx-apply-header {
	padding: 24px 24px 0;
}

.lx-apply-title {
	font-size: 18px;
	font-weight: 600;
	color: #1c1b1f;
}

.lx-apply-body {
	padding: 16px 24px;
	display: flex;
	flex-direction: column;
	gap: 12px;
}

.lx-apply-hint {
	margin: 0;
	font-size: 14px;
	color: #49454f;
	line-height: 1.5;
}

.lx-apply-field {
	display: flex;
	flex-direction: column;
	gap: 6px;
}

.lx-apply-label {
	font-size: 12px;
	font-weight: 600;
	color: #49454f;
}

.lx-required { color: #b3261e; }

.lx-apply-input {
	border: 1.5px solid #79747e;
	border-radius: 12px;
	padding: 10px 14px;
	font-size: 14px;
	font-family: inherit;
	outline: none;
	background: #fffbfe;
	color: #1c1b1f;
	transition: border-color 0.2s;
}

.lx-apply-input:focus {
	border-color: #6750a4;
	box-shadow: 0 0 0 2px rgba(103,80,164,.15);
}

.lx-apply-error {
	font-size: 12px;
	color: #b3261e;
	background: #fef2f2;
	border-radius: 8px;
	padding: 8px 12px;
}

.lx-apply-actions {
	display: flex;
	justify-content: flex-end;
	gap: 8px;
	padding: 12px 24px 20px;
}

.lx-btn-text {
	border: none;
	background: transparent;
	color: #6750a4;
	font-size: 14px;
	font-weight: 600;
	font-family: inherit;
	padding: 10px 20px;
	border-radius: 100px;
	cursor: pointer;
	transition: background 0.2s;
}

.lx-btn-text:hover { background: rgba(103,80,164,.08); }

.lx-btn-filled {
	display: flex;
	align-items: center;
	gap: 6px;
	border: none;
	background: #6750a4;
	color: #fff;
	font-size: 14px;
	font-weight: 600;
	font-family: inherit;
	padding: 10px 24px;
	border-radius: 100px;
	cursor: pointer;
	transition: background 0.2s;
}

.lx-btn-filled:hover:not(:disabled) { background: #7965af; }
.lx-btn-filled:disabled { background: #cac4d0; cursor: not-allowed; }

/* ── Spinner ────────────────────────────────────────────────────────── */
.lx-spinner {
	width: 14px;
	height: 14px;
	border: 2px solid rgba(255,255,255,.4);
	border-top-color: #fff;
	border-radius: 50%;
	animation: lx-spin 0.7s linear infinite;
	display: inline-block;
}

@keyframes lx-spin {
	to { transform: rotate(360deg); }
}

/* ── Inline message action buttons ───────────────────────────────── */
.lx-msg-actions {
	display: flex;
	gap: 8px;
	margin-top: 8px;
	flex-wrap: wrap;
}
.lx-action-btn {
	padding: 6px 16px;
	border-radius: 20px;
	border: 1.5px solid #6750A4;
	background: transparent;
	color: #6750A4;
	font-size: 13px;
	font-weight: 500;
	cursor: pointer;
	transition: background 0.15s, color 0.15s;
}
.lx-action-btn:hover {
	background: #6750A4;
	color: #fff;
}

/* ── Split diff view (MODIFY intent) ──────────────────────────────── */
.lx-split-diff {
	margin-top: 10px;
	border: 1px solid #CAC4D0;
	border-radius: 8px;
	overflow: hidden;
}
.lx-split-header {
	display: flex;
	background: #F3EDF7;
	border-bottom: 1px solid #CAC4D0;
}
.lx-split-col-label {
	flex: 1;
	padding: 4px 12px;
	font-weight: 600;
	font-size: 11px;
	color: #49454F;
	letter-spacing: 0.03em;
}
.lx-split-col-label:first-child { border-right: 1px solid #CAC4D0; }
.lx-split-body {
	background: #1C1B1F;
	max-height: 420px;
	overflow-y: auto;
}
.lx-split-row {
	display: flex;
	border-bottom: 1px solid rgba(255,255,255,0.04);
	min-height: 20px;
}
.lx-split-cell {
	flex: 1;
	margin: 0;
	padding: 1px 12px;
	font-family: "JetBrains Mono", "Fira Code", monospace;
	font-size: 12px;
	line-height: 1.5;
	color: #E6E1E5;
	white-space: pre;
	overflow: hidden;
	min-width: 0;
	border-right: 1px solid rgba(255,255,255,0.08);
}
.lx-split-cell:last-child { border-right: none; }
.lx-sdiff-del   { background: rgba(240,80,80,0.2);   color: #FF8A8A; }
.lx-sdiff-add   { background: rgba(100,220,100,0.18); color: #6EE68E; }
.lx-sdiff-hunk  { background: rgba(144,202,249,0.08); color: #90CAF9; font-style: italic; }
.lx-sdiff-empty { background: rgba(255,255,255,0.03); color: transparent; }
</style>
