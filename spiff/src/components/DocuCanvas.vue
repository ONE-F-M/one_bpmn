<template>
	<Teleport to="body">
		<div class="dc-overlay" @click.self="close">
			<div class="dc-window">

				<!-- Window header -->
				<div class="dc-window-header">
					<div class="dc-window-title">
						<span class="dc-badge">Docu</span>
						<span class="dc-subtitle">DocType Builder</span>
						<span v-if="dtName" class="dc-chip" :title="dtName">{{ dtName }}</span>
					</div>
					<button class="dc-icon-btn" @click="close" title="Close">✕</button>
				</div>

				<div class="dc-root">

					<!-- ── LEFT: Chat ──────────────────────────────────── -->
					<div class="dc-chat-panel">
						<div class="dc-messages" ref="messagesEl">
							<div v-for="msg in messages" :key="msg.id" :class="['dc-msg-row', msg.role]">
								<div class="dc-msg-body">
									<div :class="msg.role === 'user' ? 'dc-bubble-user' : 'dc-bubble-bot'">
										<div v-html="renderMarkdown(msg.content)"></div>
									</div>
									<div v-if="msg.options?.length" class="dc-options">
										<button
											v-for="(opt, oi) in msg.options"
											:key="oi"
											class="dc-option-btn"
											@click="selectOption(opt)"
										>{{ opt }}</button>
									</div>
									<div class="dc-msg-time">{{ msg.time }}</div>
								</div>
							</div>
							<div v-if="isTyping" class="dc-msg-row assistant">
								<div class="dc-bubble-bot dc-typing"><span></span><span></span><span></span></div>
							</div>
						</div>

						<div class="dc-input-area">
							<textarea
								ref="inputEl"
								v-model="inputText"
								class="dc-input"
								rows="2"
								placeholder="Describe the form you need… (Enter to send)"
								@keydown="onKeydown"
							></textarea>
							<button class="dc-send-btn" :disabled="!inputText.trim() || isTyping" @click="sendMessage()">➤</button>
						</div>
					</div>

					<!-- ── RIGHT: Form Builder ─────────────────────────── -->
					<div class="dc-builder-panel">
						<div class="dc-builder-header">
							<div class="dc-builder-field">
								<label>Form name</label>
								<input v-model="dtName" class="dc-text-input" placeholder="e.g. Vehicle Inspection" />
							</div>
							<label class="dc-checkbox-inline" title="A child table lives inside another form">
								<input type="checkbox" v-model="isChild" /> Child table
							</label>
						</div>

						<div class="dc-fields">
							<div class="dc-fields-head">
								<span>Label</span><span>ID</span><span>Type</span><span>Options</span>
								<span class="dc-col-flags">Req</span><span class="dc-col-flags">List</span><span></span>
							</div>
							<div v-if="!fields.length" class="dc-empty">
								No fields yet. Ask Docu to build the form, or add fields manually.
							</div>
							<div v-for="(f, i) in fields" :key="i" class="dc-field-row" :class="{ 'dc-layout-row': isLayout(f.fieldtype) }">
								<input v-model="f.label" class="dc-cell" placeholder="Label" />
								<input
									v-model="f.fieldname"
									class="dc-cell dc-mono"
									placeholder="fieldname"
									:disabled="isLayout(f.fieldtype)"
									@blur="autoName(f)"
								/>
								<select v-model="f.fieldtype" class="dc-cell">
									<option v-for="t in FIELD_TYPES" :key="t" :value="t">{{ t }}</option>
								</select>
								<input
									v-model="f.options"
									class="dc-cell"
									:placeholder="optionsHint(f.fieldtype)"
									:disabled="!needsOptions(f.fieldtype)"
								/>
								<span class="dc-col-flags"><input type="checkbox" v-model="f.reqd" :disabled="isLayout(f.fieldtype)" /></span>
								<span class="dc-col-flags"><input type="checkbox" v-model="f.in_list_view" :disabled="isLayout(f.fieldtype)" /></span>
								<span class="dc-row-actions">
									<button @click="moveField(i, -1)" :disabled="i === 0" title="Move up">▲</button>
									<button @click="moveField(i, 1)" :disabled="i === fields.length - 1" title="Move down">▼</button>
									<button @click="removeField(i)" title="Remove" class="dc-remove">✕</button>
								</span>
							</div>
						</div>

						<div class="dc-builder-toolbar">
							<button class="dc-add-btn" @click="addField()">+ Add field</button>
							<button class="dc-add-btn" @click="addField('Section Break')">+ Section</button>
						</div>

						<div class="dc-builder-footer">
							<span v-if="applyError" class="dc-error">{{ applyError }}</span>
							<span v-else-if="appliedName" class="dc-ok">✓ Saved “{{ appliedName }}”</span>
							<button
								class="dc-apply-btn"
								:disabled="applying || !dtName.trim() || !fields.length"
								@click="applyDoctype"
							>
								{{ applying ? "Applying…" : "Apply to system" }}
							</button>
						</div>
					</div>

				</div>
			</div>
		</div>
	</Teleport>
</template>

<script setup>
import { ref, reactive, onMounted, nextTick } from "vue";
import { frappeRequest } from "frappe-ui";
import { marked } from "marked";
import DOMPurify from "dompurify";

marked.setOptions({ gfm: true, breaks: true });

const props = defineProps({
	element:        { type: Object, default: null },
	doctype:        { type: String, default: "" },
	attr:           { type: String, default: "" },
	processContext: { type: Object, default: null },
});
const emit = defineEmits(["close", "applied"]);

const API = "/api/method/one_bpmn.api.docu_api.";

// Field types — mirrors ALLOWED_FIELDTYPES in security/doctype_validator.py.
const FIELD_TYPES = [
	"Data", "Small Text", "Text", "Long Text", "Text Editor", "Code", "Markdown Editor",
	"Int", "Float", "Currency", "Percent", "Check",
	"Date", "Datetime", "Time", "Duration",
	"Select", "Link", "Dynamic Link", "Table", "Table MultiSelect",
	"Attach", "Attach Image", "Signature", "Color", "Rating", "Phone", "Password", "Read Only",
	"Section Break", "Column Break", "Tab Break", "HTML", "Heading",
];
const OPTIONS_TYPES = new Set(["Select", "Link", "Dynamic Link", "Table", "Table MultiSelect"]);
const LAYOUT_TYPES  = new Set(["Section Break", "Column Break", "Tab Break", "HTML", "Heading"]);

// ── State ──────────────────────────────────────────────────────────────
const messages   = ref([]);
const isTyping    = ref(false);
const inputText   = ref("");
const messagesEl  = ref(null);
const inputEl     = ref(null);
const sessionId   = ref(`docu-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`);

const dtName    = ref(props.doctype || "");
const dtModule  = ref("ONE BPMN");
const isChild   = ref(false);
const fields    = ref([]);

const applying    = ref(false);
const applyError  = ref("");
const appliedName = ref("");

let msgSeq = 0;
const makeId = () => `m${++msgSeq}`;
const nowTime = () => new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });

function renderMarkdown(text) {
	return DOMPurify.sanitize(marked.parse(text || ""));
}
function isLayout(t) { return LAYOUT_TYPES.has(t); }
function needsOptions(t) { return OPTIONS_TYPES.has(t); }
function optionsHint(t) {
	if (t === "Link" || t === "Table" || t === "Table MultiSelect") return "Target DocType";
	if (t === "Dynamic Link") return "fieldname holding DocType";
	if (t === "Select") return "one choice per line";
	return "—";
}

function pushMsg(role, content, extra = {}) {
	messages.value.push({ id: makeId(), role, content, time: nowTime(), ...extra });
	scrollDown();
}
function scrollDown() {
	nextTick(() => { if (messagesEl.value) messagesEl.value.scrollTop = messagesEl.value.scrollHeight; });
}

// ── Builder helpers ──────────────────────────────────────────────────────
function blankField(fieldtype = "Data") {
	return reactive({
		fieldname: "", label: "", fieldtype, options: "",
		reqd: false, in_list_view: false, unique: false, read_only: false, default: "",
	});
}
function addField(fieldtype = "Data") {
	fields.value.push(blankField(fieldtype));
}
function removeField(i) { fields.value.splice(i, 1); }
function moveField(i, dir) {
	const j = i + dir;
	if (j < 0 || j >= fields.value.length) return;
	const arr = fields.value;
	[arr[i], arr[j]] = [arr[j], arr[i]];
}
function autoName(f) {
	if (!f.fieldname && f.label && !isLayout(f.fieldtype)) {
		f.fieldname = f.label.trim().toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "");
	}
}

function loadIr(ir) {
	if (!ir) return;
	if (ir.doctype_name) dtName.value = ir.doctype_name;
	if (ir.module) dtModule.value = ir.module;
	isChild.value = !!ir.is_child_table;
	fields.value = (ir.fields || []).map((f) => reactive({
		fieldname: f.fieldname || "",
		label: f.label || "",
		fieldtype: f.fieldtype || "Data",
		options: f.options || "",
		reqd: !!f.reqd,
		in_list_view: !!f.in_list_view,
		unique: !!f.unique,
		read_only: !!f.read_only,
		default: f.default || "",
	}));
	appliedName.value = "";
	applyError.value = "";
}

function currentIr() {
	return {
		doctype_name: dtName.value.trim(),
		module: dtModule.value || "ONE BPMN",
		is_child_table: isChild.value,
		fields: fields.value.map((f) => ({
			fieldname: isLayout(f.fieldtype) ? "" : (f.fieldname || "").trim(),
			label: f.label || "",
			fieldtype: f.fieldtype,
			options: (f.options || "").trim(),
			reqd: f.reqd ? 1 : 0,
			in_list_view: f.in_list_view ? 1 : 0,
			unique: f.unique ? 1 : 0,
			read_only: f.read_only ? 1 : 0,
			default: f.default || "",
		})),
	};
}

// ── API calls ──────────────────────────────────────────────────────────
async function loadSchema(dt) {
	try {
		const res = await frappeRequest({ url: `${API}get_doctype_schema`, params: { doctype: dt } });
		if (res?.exists && res.doctype_ir) loadIr(res.doctype_ir);
	} catch (e) { /* new doctype — nothing to load */ }
}

function chatHistoryPayload() {
	return messages.value
		.filter((m) => m.role === "user" || m.role === "assistant")
		.slice(-10)
		.map((m) => ({ role: m.role, content: m.content }));
}

async function sendMessage(preset) {
	const text = (preset ?? inputText.value).trim();
	if (!text || isTyping.value) return;
	pushMsg("user", text);
	inputText.value = "";
	isTyping.value = true;
	try {
		const res = await frappeRequest({
			url: `${API}docu_chat`,
			method: "POST",
			params: {
				message: text,
				session_id: sessionId.value,
				chat_history: chatHistoryPayload(),
				doctype: dtName.value || props.doctype || "",
				target_module: dtModule.value || "",
				process_context: props.processContext || null,
			},
		});
		const reply = res?.response || "Sorry, I couldn't process that.";
		pushMsg("assistant", reply, { options: res?.options || null });
		if (res?.doctype_ir) loadIr(res.doctype_ir);
	} catch (e) {
		pushMsg("assistant", "Something went wrong. Please try again.");
	} finally {
		isTyping.value = false;
	}
}

function selectOption(opt) { sendMessage(opt); }

function onKeydown(e) {
	if (e.key === "Enter" && !e.shiftKey) {
		e.preventDefault();
		sendMessage();
	}
}

async function applyDoctype() {
	applyError.value = "";
	appliedName.value = "";
	applying.value = true;
	try {
		const res = await frappeRequest({
			url: `${API}apply_doctype`,
			method: "POST",
			params: { ir: JSON.stringify(currentIr()) },
		});
		const name = res?.name || dtName.value;
		appliedName.value = name;
		const verb = { created: "created", updated: "updated", fields_added: "updated", unchanged: "already up to date" }[res?.action] || "saved";
		pushMsg("assistant", `✓ **${name}** ${verb}. You can now use it on the shape. [Open it](${res?.url || "#"})`);
		emit("applied", name);
	} catch (e) {
		applyError.value = (e && (e.message || e._server_messages)) ? String(e.message || e._server_messages) : "Could not apply the form.";
		pushMsg("assistant", `⚠️ I couldn't apply the form: ${applyError.value}`);
	} finally {
		applying.value = false;
	}
}

function close() { emit("close"); }

// ── Init ──────────────────────────────────────────────────────────────
onMounted(async () => {
	if (props.doctype) {
		// A doctype is already selected on the shape — load its form builder view
		// on the right and greet with a change-focused message (AC: WI Docu greeting).
		await loadSchema(props.doctype);
		const dt = props.doctype;
		pushMsg(
			"assistant",
			`Hello, I am **Docu**.\n` +
			`Happy to help with changes to **${dt}** doctype.\n` +
			`How would you like me to assist in redefining the **${dt}** doctype or its fields?`,
		);
	} else {
		// No doctype selected on the shape — greet with a create-focused message and
		// tell the user how to switch to change-mode (AC: Docu no-doctype greeting).
		pushMsg(
			"assistant",
			`Hello, I am **Docu**.\n` +
			`Happy to help with creating doctypes.\n` +
			`If the doctype already exists and you just want to make changes, please close this window, ` +
			`select the doctype in the relevant shape's property panel and click on the "Launch Docu" button again.`,
		);
	}
	nextTick(() => inputEl.value?.focus());
});
</script>

<style scoped>
.dc-overlay {
	position: fixed; inset: 0; z-index: 2000;
	background: rgba(15, 23, 42, 0.55);
	display: flex; align-items: center; justify-content: center;
}
.dc-window {
	width: min(1180px, 96vw); height: min(760px, 92vh);
	background: #fff; border-radius: 12px; overflow: hidden;
	display: flex; flex-direction: column;
	box-shadow: 0 24px 60px rgba(0, 0, 0, 0.35);
}
.dc-window-header {
	display: flex; align-items: center; justify-content: space-between;
	padding: 10px 16px; border-bottom: 1px solid #e5e7eb; background: #f8fafc;
}
.dc-window-title { display: flex; align-items: center; gap: 8px; }
.dc-badge { background: #4f46e5; color: #fff; font-weight: 700; font-size: 12px; padding: 2px 8px; border-radius: 6px; }
.dc-subtitle { font-size: 13px; color: #475569; font-weight: 600; }
.dc-chip { font-size: 12px; color: #4f46e5; background: #eef2ff; padding: 2px 8px; border-radius: 10px; max-width: 260px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.dc-icon-btn { border: none; background: transparent; font-size: 16px; cursor: pointer; color: #64748b; }

.dc-root { flex: 1; display: flex; min-height: 0; }

/* Chat */
.dc-chat-panel { width: 42%; display: flex; flex-direction: column; border-right: 1px solid #e5e7eb; min-width: 0; }
.dc-messages { flex: 1; overflow-y: auto; padding: 14px; display: flex; flex-direction: column; gap: 10px; }
.dc-msg-row { display: flex; }
.dc-msg-row.user { justify-content: flex-end; }
.dc-msg-body { max-width: 88%; }
.dc-bubble-user { background: #4f46e5; color: #fff; padding: 8px 12px; border-radius: 12px 12px 2px 12px; font-size: 13px; }
.dc-bubble-bot { background: #f1f5f9; color: #0f172a; padding: 8px 12px; border-radius: 12px 12px 12px 2px; font-size: 13px; }
.dc-bubble-bot :deep(p) { margin: 0 0 6px; } .dc-bubble-bot :deep(p:last-child) { margin: 0; }
.dc-bubble-bot :deep(a) { color: #4f46e5; }
.dc-msg-time { font-size: 10px; color: #94a3b8; margin-top: 3px; }
.dc-msg-row.user .dc-msg-time { text-align: right; }
.dc-options { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 6px; }
.dc-option-btn { border: 1px solid #c7d2fe; background: #eef2ff; color: #4338ca; border-radius: 14px; padding: 4px 12px; font-size: 12px; cursor: pointer; }
.dc-option-btn:hover { background: #e0e7ff; }
.dc-typing span { display: inline-block; width: 6px; height: 6px; margin: 0 1px; background: #94a3b8; border-radius: 50%; animation: dc-blink 1.2s infinite; }
.dc-typing span:nth-child(2) { animation-delay: .2s; } .dc-typing span:nth-child(3) { animation-delay: .4s; }
@keyframes dc-blink { 0%, 60%, 100% { opacity: .3; } 30% { opacity: 1; } }
.dc-input-area { display: flex; gap: 8px; padding: 10px; border-top: 1px solid #e5e7eb; }
.dc-input { flex: 1; resize: none; border: 1px solid #cbd5e1; border-radius: 8px; padding: 8px; font-size: 13px; font-family: inherit; }
.dc-send-btn { border: none; background: #4f46e5; color: #fff; border-radius: 8px; width: 40px; cursor: pointer; font-size: 15px; }
.dc-send-btn:disabled { background: #c7d2fe; cursor: not-allowed; }

/* Builder */
.dc-builder-panel { flex: 1; display: flex; flex-direction: column; min-width: 0; background: #fcfcfd; }
.dc-builder-header { display: flex; align-items: flex-end; gap: 16px; padding: 12px 16px; border-bottom: 1px solid #e5e7eb; }
.dc-builder-field { flex: 1; display: flex; flex-direction: column; gap: 3px; }
.dc-builder-field label { font-size: 11px; color: #64748b; font-weight: 600; }
.dc-text-input { border: 1px solid #cbd5e1; border-radius: 6px; padding: 6px 8px; font-size: 13px; }
.dc-checkbox-inline { font-size: 12px; color: #475569; display: flex; align-items: center; gap: 5px; padding-bottom: 6px; }
.dc-fields { flex: 1; overflow-y: auto; padding: 8px 12px; }
.dc-fields-head, .dc-field-row {
	display: grid;
	grid-template-columns: 1.3fr 1fr 1.1fr 1.2fr 42px 42px 70px;
	gap: 6px; align-items: center;
}
.dc-fields-head { font-size: 10px; text-transform: uppercase; color: #94a3b8; font-weight: 700; padding: 4px 2px; position: sticky; top: 0; background: #fcfcfd; }
.dc-field-row { padding: 3px 0; }
.dc-layout-row { background: #f8fafc; border-radius: 6px; }
.dc-cell { border: 1px solid #d7dde5; border-radius: 5px; padding: 5px 6px; font-size: 12px; min-width: 0; width: 100%; }
.dc-cell:disabled { background: #f1f5f9; color: #94a3b8; }
.dc-mono { font-family: ui-monospace, monospace; }
.dc-col-flags { text-align: center; }
.dc-row-actions { display: flex; gap: 2px; }
.dc-row-actions button { border: none; background: transparent; cursor: pointer; color: #94a3b8; font-size: 11px; padding: 2px; }
.dc-row-actions button:disabled { opacity: .3; cursor: not-allowed; }
.dc-remove { color: #ef4444 !important; }
.dc-empty { color: #94a3b8; font-size: 13px; padding: 24px; text-align: center; }
.dc-builder-toolbar { display: flex; gap: 8px; padding: 8px 16px; border-top: 1px solid #eef1f5; }
.dc-add-btn { border: 1px dashed #c7d2fe; background: #fff; color: #4f46e5; border-radius: 6px; padding: 5px 12px; font-size: 12px; cursor: pointer; }
.dc-add-btn:hover { background: #eef2ff; }
.dc-builder-footer { display: flex; align-items: center; justify-content: flex-end; gap: 12px; padding: 10px 16px; border-top: 1px solid #e5e7eb; }
.dc-error { color: #dc2626; font-size: 12px; }
.dc-ok { color: #16a34a; font-size: 12px; font-weight: 600; }
.dc-apply-btn { border: none; background: #16a34a; color: #fff; border-radius: 8px; padding: 8px 18px; font-size: 13px; font-weight: 600; cursor: pointer; }
.dc-apply-btn:disabled { background: #a7f3d0; cursor: not-allowed; }
</style>
