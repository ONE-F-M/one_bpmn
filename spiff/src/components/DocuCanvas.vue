<template>
	<Teleport to="body">
		<div class="dc-overlay" @click.self="close">
			<div class="dc-window">

				<!-- Window header -->
				<div class="dc-window-header">
					<div class="dc-window-title">
						<span class="dc-badge">Docu</span>
						<span class="dc-subtitle">DocType Builder</span>
						<span v-if="dtName" class="dc-dt-chip" :title="dtName">{{ dtName }}</span>
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
								placeholder="Describe the DocType you need… (Enter to send)"
								@keydown="onKeydown"
							></textarea>
							<button class="dc-send-btn" :disabled="!inputText.trim() || isTyping" @click="sendMessage()">➤</button>
						</div>
					</div>

					<!-- ── MIDDLE: Visual form builder ─────────────────── -->
					<div class="dc-builder-panel">
						<div class="dc-builder-topbar">
							<div class="dc-form-name">
								<input v-model="dtName" class="dc-name-input" placeholder="DocType name (e.g. Vehicle Inspection)"
									@focus="selectForm()" />
							</div>
							<div class="dc-hist-group">
								<button class="dc-icon-sm" :disabled="!canUndo" @click="undo" title="Undo (Ctrl+Z)">↶</button>
								<button class="dc-icon-sm" :disabled="!canRedo" @click="redo" title="Redo (Ctrl+Shift+Z)">↷</button>
								<button class="dc-add-btn" @click="showTemplates = true" title="Start from a template">Templates</button>
							</div>
							<div class="dc-add-group">
								<button class="dc-add-btn" @click="addField()" title="Add a field">+ Field</button>
								<button class="dc-add-btn" @click="addSection()" title="Add a section">+ Section</button>
								<button class="dc-add-btn" @click="addColumn()" title="Add a column">+ Column</button>
								<button class="dc-add-btn" @click="addTab()" title="Add a tab">+ Tab</button>
								<button class="dc-gear-btn" :class="{ active: sel.type === 'form' }" @click="selectForm()" title="DocType settings">⚙</button>
							</div>
						</div>

						<!-- Tabs strip -->
						<draggable
							v-if="tabs.length"
							:list="tabs"
							item-key="id"
							class="dc-tabs"
							:animation="150"
						>
							<template #item="{ element: tab, index }">
								<div
									class="dc-tab"
									:class="{ active: index === activeTabIndex, sel: isSel('tab', tab) }"
									@click="activeTabIndex = index"
									@dblclick="selectContainer('tab', tab)"
								>
									<span class="dc-tab-label">{{ tabLabel(tab, index) }}</span>
									<button class="dc-tab-edit" @click.stop="selectContainer('tab', tab)" title="Tab properties">⚙</button>
								</div>
							</template>
						</draggable>

						<!-- Active tab body -->
						<div class="dc-canvas" v-if="activeTab">
							<draggable
								:list="activeTab.sections"
								item-key="id"
								group="dc-sections"
								handle=".dc-section-grip"
								class="dc-sections"
								:animation="150"
							>
								<template #item="{ element: section }">
									<div class="dc-section" :class="{ sel: isSel('section', section) }">
										<div class="dc-section-bar">
											<span class="dc-section-grip" title="Drag to reorder section">⠿</span>
											<span class="dc-section-title" @click="selectContainer('section', section)">
												{{ sectionLabel(section) }}
											</span>
											<button class="dc-mini-btn" @click.stop="addColumn(section)" title="Add column">+ Col</button>
										</div>
										<draggable
											:list="section.columns"
											item-key="id"
											group="dc-columns"
											class="dc-columns"
											:animation="150"
										>
											<template #item="{ element: column }">
												<div
													class="dc-column"
													:class="{ sel: isSel('column', column) }"
													@click.self="selectContainer('column', column)"
												>
													<draggable
														:list="column.fields"
														item-key="id"
														group="dc-fields"
														class="dc-col-fields"
														:animation="150"
													>
														<template #item="{ element: fld }">
															<div
																class="dc-chip"
																:class="{ sel: isSelField(fld) }"
																:title="fld.df.fieldname || fld.df.label"
																@click.stop="selectField(fld)"
															>
																<span class="dc-chip-grip">⠿</span>
																<span class="dc-chip-main">
																	<span class="dc-chip-label">{{ fld.df.label || "(No label)" }}</span>
																	<span class="dc-chip-type">{{ fld.df.fieldtype }}</span>
																</span>
																<span v-if="fld.df.reqd" class="dc-req" title="Mandatory">*</span>
																<button class="dc-chip-x" @click.stop="removeField(column, fld)" title="Remove">✕</button>
															</div>
														</template>
													</draggable>
													<button class="dc-add-inline" @click.stop="addFieldToColumn(column)">+ field</button>
												</div>
											</template>
										</draggable>
									</div>
								</template>
							</draggable>
							<button class="dc-add-section" @click="addSection()">+ Add section</button>
						</div>
					</div>

					<!-- ── RIGHT: Properties sidebar ───────────────────── -->
					<div class="dc-props-panel">

						<!-- Field properties -->
						<template v-if="sel.type === 'field' && sel.node">
							<div class="dc-props-head">Field properties</div>
							<div class="dc-prop">
								<label>Label</label>
								<input v-model="sel.node.df.label" class="dc-prop-input" @blur="autoName(sel.node.df)" />
							</div>
							<div class="dc-prop">
								<label>Name (fieldname)</label>
								<input v-model="sel.node.df.fieldname" class="dc-prop-input dc-mono" placeholder="snake_case" />
							</div>
							<div class="dc-prop">
								<label>Type</label>
								<select v-model="sel.node.df.fieldtype" class="dc-prop-input">
									<option v-for="t in CONTENT_TYPES" :key="t" :value="t">{{ t }}</option>
								</select>
							</div>
							<div class="dc-prop" v-if="needsOptions(sel.node.df.fieldtype)">
								<label>Options — {{ optionsHint(sel.node.df.fieldtype) }}</label>
								<textarea
									v-if="sel.node.df.fieldtype === 'Select'"
									v-model="sel.node.df.options"
									class="dc-prop-input"
									rows="4"
									placeholder="One choice per line"
								></textarea>
								<input v-else v-model="sel.node.df.options" class="dc-prop-input" :placeholder="optionsHint(sel.node.df.fieldtype)" />
							</div>
							<div class="dc-prop">
								<label>Default</label>
								<input v-model="sel.node.df.default" class="dc-prop-input" />
							</div>
							<div class="dc-prop">
								<label>Description</label>
								<input v-model="sel.node.df.description" class="dc-prop-input" />
							</div>
							<div class="dc-prop">
								<label>Depends on (eval)</label>
								<input v-model="sel.node.df.depends_on" class="dc-prop-input dc-mono" placeholder="eval:doc.status=='Open'" />
							</div>
							<div class="dc-flags">
								<label><input type="checkbox" v-model="sel.node.df.reqd" /> Mandatory</label>
								<label><input type="checkbox" v-model="sel.node.df.unique" /> Unique</label>
								<label><input type="checkbox" v-model="sel.node.df.in_list_view" /> In list view</label>
								<label><input type="checkbox" v-model="sel.node.df.in_standard_filter" /> Std filter</label>
								<label><input type="checkbox" v-model="sel.node.df.read_only" /> Read only</label>
								<label><input type="checkbox" v-model="sel.node.df.hidden" /> Hidden</label>
								<label><input type="checkbox" v-model="sel.node.df.bold" /> Bold</label>
							</div>
							<button class="dc-delete-btn" @click="deleteSelected()">Delete field</button>
						</template>

						<!-- Section / Column / Tab properties -->
						<template v-else-if="(sel.type === 'section' || sel.type === 'column' || sel.type === 'tab') && sel.node">
							<div class="dc-props-head">{{ capitalize(sel.type) }} properties</div>
							<div class="dc-prop">
								<label>Label</label>
								<input v-model="sel.node.df.label" class="dc-prop-input" :placeholder="sel.type + ' title (optional)'" />
							</div>
							<div class="dc-prop" v-if="sel.type !== 'column'">
								<label>Description</label>
								<input v-model="sel.node.df.description" class="dc-prop-input" />
							</div>
							<label class="dc-switch" v-if="sel.type === 'section'">
								<input type="checkbox" v-model="sel.node.df.collapsible" />
								<span class="dc-switch-track"><span class="dc-switch-thumb"></span></span>
								<span class="dc-switch-text">Collapsible section</span>
							</label>
							<p class="dc-hint">Drag {{ sel.type === 'tab' ? 'tabs' : sel.type + 's' }} to rearrange. Fields drag between columns.</p>
							<button class="dc-delete-btn" @click="deleteSelected()">Delete {{ sel.type }}</button>
						</template>

						<!-- DocType settings -->
						<template v-else>
							<div class="dc-props-head">DocType settings</div>
							<div class="dc-prop">
								<label>DocType name</label>
								<input v-model="dtName" class="dc-prop-input" placeholder="e.g. Vehicle Inspection" />
							</div>
							<div class="dc-prop">
								<label>Module</label>
								<select v-model="dtModule" class="dc-prop-input">
									<option v-for="m in moduleOptions" :key="m" :value="m">{{ m }}</option>
								</select>
							</div>
							<div class="dc-prop">
								<label>Naming (autoname)</label>
								<input v-model="dtAutoname" class="dc-prop-input dc-mono" placeholder="e.g. field:vehicle_no or format:VI-.#####" />
							</div>
							<label class="dc-switch">
								<input type="checkbox" v-model="isChild" />
								<span class="dc-switch-track"><span class="dc-switch-thumb"></span></span>
								<span class="dc-switch-text">Child table (lives inside another DocType)</span>
							</label>
							<p class="dc-hint">
								Select a field, section, column or tab to edit its properties.
								Ask Docu on the left to build or change the DocType, then drag to arrange.
							</p>
						</template>
					</div>

				</div>

				<!-- Footer -->
				<div class="dc-window-footer">
					<span v-if="applyError" class="dc-error">{{ applyError }}</span>
					<span v-else-if="appliedName" class="dc-ok">✓ Saved “{{ appliedName }}”</span>
					<span v-else class="dc-count">{{ contentCount }} field{{ contentCount === 1 ? "" : "s" }}</span>
					<button
						class="dc-apply-btn"
						:disabled="applying || previewing || !dtName.trim() || !contentCount"
						@click="requestApply"
					>
						{{ previewing ? "Checking…" : (applying ? "Applying…" : "Apply to system") }}
					</button>
				</div>

				<!-- Apply confirmation (#3 / #4) -->
				<div v-if="showConfirm && previewData" class="dc-modal-scrim" @click.self="showConfirm = false">
					<div class="dc-modal">
						<div class="dc-modal-title">Confirm change</div>
						<p class="dc-modal-summary">{{ previewData.summary }}</p>
						<div v-if="previewData.diff" class="dc-diff">
							<div v-if="previewData.diff.added.length" class="dc-diff-line dc-diff-add">＋ Adds: {{ previewData.diff.added.join(", ") }}</div>
							<div v-if="previewData.diff.changed.length" class="dc-diff-line dc-diff-chg">～ Changes: {{ previewData.diff.changed.join(", ") }}</div>
							<div v-if="previewData.diff.removed.length" class="dc-diff-line dc-diff-rem">− Removes: {{ previewData.diff.removed.join(", ") }}</div>
						</div>
						<div v-if="previewData.warnings && previewData.warnings.length" class="dc-warn">
							<div v-for="(w, wi) in previewData.warnings" :key="wi">⚠ {{ w }}</div>
						</div>
						<div class="dc-modal-actions">
							<button class="dc-btn-text" @click="showConfirm = false">Cancel</button>
							<button class="dc-btn-filled" :class="{ 'dc-btn-danger': previewData.destructive }" :disabled="applying" @click="confirmApply">
								{{ applying ? "Applying…" : (previewData.destructive ? "Apply anyway" : "Confirm & apply") }}
							</button>
						</div>
					</div>
				</div>

				<!-- Template picker (#12) -->
				<div v-if="showTemplates" class="dc-modal-scrim" @click.self="showTemplates = false">
					<div class="dc-modal">
						<div class="dc-modal-title">Start from a template</div>
						<p class="dc-modal-summary">Pick a starting point — you can change everything afterwards.</p>
						<div class="dc-template-list">
							<button v-for="t in TEMPLATES" :key="t.ir.doctype_name" class="dc-template-item" @click="pickTemplate(t)">
								<span class="dc-template-name">{{ t.name }}</span>
								<span class="dc-template-desc">{{ t.desc }}</span>
							</button>
						</div>
						<div class="dc-modal-actions">
							<button class="dc-btn-text" @click="showTemplates = false">Cancel</button>
						</div>
					</div>
				</div>
			</div>
		</div>
	</Teleport>
</template>

<script setup>
import { ref, reactive, computed, watch, onMounted, onBeforeUnmount, nextTick } from "vue";
import { frappeRequest } from "frappe-ui";
import { marked } from "marked";
import DOMPurify from "dompurify";
import draggable from "vuedraggable";

marked.setOptions({ gfm: true, breaks: true });

const props = defineProps({
	element:        { type: Object, default: null },
	doctype:        { type: String, default: "" },
	attr:           { type: String, default: "" },
	processContext: { type: Object, default: null },
});
const emit = defineEmits(["close", "applied"]);

const API = "/api/method/one_bpmn.api.docu_api.";

// Starter templates (#12) — plain-language OneFM forms the user can adapt.
const TEMPLATES = [
	{ name: "Visitor Sign-In", desc: "Log visitors at the gate", ir: {
		doctype_name: "Visitor Sign In", module: "ONE BPMN", autoname: "format:VSI-.#####", fields: [
			{ fieldname: "visitor_name", label: "Visitor Name", fieldtype: "Data", reqd: 1, in_list_view: 1 },
			{ fieldname: "phone_number", label: "Phone Number", fieldtype: "Phone" },
			{ fieldname: "company", label: "Company", fieldtype: "Data" },
			{ fieldname: "person_to_meet", label: "Person to Meet", fieldtype: "Data" },
			{ fieldname: "check_in", label: "Check-In Time", fieldtype: "Datetime", default: "Now", in_list_view: 1 },
			{ fieldname: "check_out", label: "Check-Out Time", fieldtype: "Datetime" },
			{ fieldname: "notes", label: "Notes", fieldtype: "Small Text" },
		] } },
	{ name: "Leave Request", desc: "Staff time-off requests", ir: {
		doctype_name: "Staff Leave Request", module: "ONE BPMN", fields: [
			{ fieldname: "employee_name", label: "Employee Name", fieldtype: "Data", reqd: 1, in_list_view: 1 },
			{ fieldname: "leave_type", label: "Leave Type", fieldtype: "Select", options: "Annual\nSick\nUnpaid\nEmergency", reqd: 1 },
			{ fieldname: "from_date", label: "From", fieldtype: "Date", reqd: 1 },
			{ fieldname: "to_date", label: "To", fieldtype: "Date", reqd: 1 },
			{ fieldname: "reason", label: "Reason", fieldtype: "Small Text" },
		] } },
	{ name: "Incident Report", desc: "Report on-site incidents", ir: {
		doctype_name: "Incident Report", module: "ONE BPMN", autoname: "format:INC-.#####", fields: [
			{ fieldname: "occurred_at", label: "When It Happened", fieldtype: "Datetime", reqd: 1, in_list_view: 1 },
			{ fieldname: "location", label: "Location", fieldtype: "Data", in_list_view: 1 },
			{ fieldname: "severity", label: "Severity", fieldtype: "Select", options: "Low\nMedium\nHigh\nCritical", reqd: 1 },
			{ fieldname: "sec_desc", label: "Details", fieldtype: "Section Break" },
			{ fieldname: "description", label: "What Happened", fieldtype: "Text", reqd: 1 },
			{ fieldname: "action_taken", label: "Action Taken", fieldtype: "Text" },
		] } },
	{ name: "Equipment Handover", desc: "Track items given to staff", ir: {
		doctype_name: "Equipment Handover", module: "ONE BPMN", fields: [
			{ fieldname: "worker", label: "Worker", fieldtype: "Data", reqd: 1, in_list_view: 1 },
			{ fieldname: "date_out", label: "Date Given Out", fieldtype: "Date", default: "Today" },
			{ fieldname: "items", label: "Items", fieldtype: "Table", child_fields: [
				{ fieldname: "item", label: "Item", fieldtype: "Data" },
				{ fieldname: "quantity", label: "Quantity", fieldtype: "Int" },
			] },
			{ fieldname: "returned", label: "Returned", fieldtype: "Check" },
		] } },
];

// Field types — mirrors ALLOWED_FIELDTYPES in security/doctype_validator.py.
const FIELD_TYPES = [
	"Data", "Small Text", "Text", "Long Text", "Text Editor", "Code", "Markdown Editor",
	"Int", "Float", "Currency", "Percent", "Check",
	"Date", "Datetime", "Time", "Duration",
	"Select", "Link", "Dynamic Link", "Table", "Table MultiSelect",
	"Attach", "Attach Image", "Signature", "Color", "Rating", "Phone", "Password", "Read Only",
	"HTML", "Heading",
];
// Structural breaks are the layout delimiters of the field list (validator's
// _LAYOUT_FIELDTYPES). They carry no fieldname. HTML/Heading are content fields
// that live inside a column, so they are NOT structural.
const STRUCTURAL = new Set(["Section Break", "Column Break", "Tab Break"]);
// Types the properties-panel dropdown offers (structure is managed via the
// add-section/column/tab buttons + drag, exactly like Frappe's builder).
const CONTENT_TYPES = FIELD_TYPES.filter((t) => !STRUCTURAL.has(t));
const OPTIONS_TYPES = new Set(["Select", "Link", "Dynamic Link", "Table", "Table MultiSelect"]);
// Field boolean flags coerced to 0/1 on the way to the backend.
const FIELD_FLAGS = [
	"reqd", "in_list_view", "unique", "read_only", "in_standard_filter",
	"hidden", "bold", "non_negative", "collapsible",
];

// ── Chat state ─────────────────────────────────────────────────────────
const messages   = ref([]);
const isTyping    = ref(false);
const inputText   = ref("");
const messagesEl  = ref(null);
const inputEl     = ref(null);
const sessionId   = ref(`docu-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`);
const conversationName = ref(null);  // set by the backend on the first turn; reused after
let pollTimer = null;                 // setTimeout handle for the status poll loop
let pollCancelled = false;            // set on close/unmount to stop polling

// ── DocType state ──────────────────────────────────────────────────────
const dtName     = ref(props.doctype || "");
const dtModule   = ref("ONE BPMN");
const dtAutoname = ref("");
const isChild    = ref(false);
const modules    = ref([]);   // Module Def names for the module picker
// Always include the current module (e.g. an agent-supplied one) so it stays selectable.
const moduleOptions = computed(() => {
	const list = modules.value.slice();
	for (const m of [dtModule.value, "ONE BPMN"]) {
		if (m && !list.includes(m)) list.unshift(m);
	}
	return list;
});

// ── Builder tree (tabs → sections → columns → fields) ──────────────────
// The tree is the working model while editing; the flat IR fields[] the
// backend expects is derived on demand in currentIr(). Each node wraps a
// `df` (the real field dict — spread-preserved so agent-generated attrs
// survive the round-trip) and keeps its own drag id off the df.
const tabs = ref([]);
const activeTabIndex = ref(0);
const activeTab = computed(() => tabs.value[activeTabIndex.value] || null);

// selection: { type: 'form'|'field'|'section'|'column'|'tab', node }
const sel = reactive({ type: "form", node: null });

let uid = 0;
const nid = () => `n${++uid}`;

const applying    = ref(false);
const applyError  = ref("");
const appliedName = ref("");

// Apply confirmation (#3/#4) + template picker (#12)
const previewing   = ref(false);
const showConfirm  = ref(false);
const previewData  = ref(null);
const showTemplates = ref(false);

// Undo/redo (#12) — snapshot the flat IR; restore rebuilds the tree.
const history   = ref([]);
const histIndex = ref(-1);
let isRestoring = false;
let snapTimer   = null;
const canUndo = computed(() => histIndex.value > 0);
const canRedo = computed(() => histIndex.value < history.value.length - 1);

let msgSeq = 0;
const makeId = () => `m${++msgSeq}`;
const nowTime = () => new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });

function renderMarkdown(text) { return DOMPurify.sanitize(marked.parse(text || "")); }
function capitalize(s) { return s ? s[0].toUpperCase() + s.slice(1) : s; }
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

// ── Tree node factories ────────────────────────────────────────────────
function normalizeDf(f) {
	// Preserve every incoming attribute (spread) so props the builder does not
	// render — fetch_from, precision, mandatory_depends_on, … — survive the
	// round-trip; then coerce the UI-bound flags to booleans for the checkboxes.
	const df = { ...f };
	df.label = f.label || "";
	df.fieldname = f.fieldname || "";
	df.fieldtype = f.fieldtype || "Data";
	df.options = f.options || "";
	df.default = f.default || "";
	df.description = f.description || "";
	df.depends_on = f.depends_on || "";
	for (const flag of FIELD_FLAGS) df[flag] = !!f[flag];
	return reactive(df);
}
function makeBreak(fieldtype) {
	return reactive({ fieldtype, label: "", fieldname: "", description: "" });
}
function wrapTab(df)     { return reactive({ id: nid(), df: df || null, sections: [] }); }
function wrapSection(df) { return reactive({ id: nid(), df: df || null, columns: [] }); }
function wrapColumn(df)  { return reactive({ id: nid(), df: df || null, fields: [] }); }
function wrapField(df)   { return reactive({ id: nid(), df }); }

// flat fields[] → tree (lazy: implicit containers created only when needed, so a
// leading break never leaves an empty container in front of it)
function buildTree(raw) {
	const t = [];
	let ct = null, cs = null, cc = null;
	const pushTab = (df) => { ct = wrapTab(df); t.push(ct); cs = null; cc = null; };
	const pushSection = (df) => { if (!ct) pushTab(null); cs = wrapSection(df); ct.sections.push(cs); cc = null; };
	const pushColumn = (df) => { if (!cs) pushSection(null); cc = wrapColumn(df); cs.columns.push(cc); };
	const pushField = (df) => { if (!cc) pushColumn(null); cc.fields.push(wrapField(df)); };

	for (const f of raw || []) {
		const df = normalizeDf(f);
		switch (df.fieldtype) {
			case "Tab Break":    pushTab(df); break;
			case "Section Break": pushSection(df); break;
			case "Column Break": pushColumn(df); break;
			default:             pushField(df);
		}
	}
	tabs.value = t;
	ensureStructure();
	activeTabIndex.value = 0;
}

// Guarantee there is always at least one tab / section / column to drop into.
function ensureStructure() {
	if (!tabs.value.length) tabs.value.push(wrapTab(null));
	for (const tab of tabs.value) {
		if (!tab.sections.length) tab.sections.push(wrapSection(null));
		for (const s of tab.sections) {
			if (!s.columns.length) s.columns.push(wrapColumn(null));
		}
	}
	if (activeTabIndex.value >= tabs.value.length) activeTabIndex.value = 0;
}

// tree → flat fields[] (implicit containers with df=null emit nothing)
function flatten() {
	const out = [];
	for (const tab of tabs.value) {
		if (tab.df) out.push(tab.df);
		for (const s of tab.sections) {
			if (s.df) out.push(s.df);
			for (const c of s.columns) {
				if (c.df) out.push(c.df);
				for (const f of c.fields) out.push(f.df);
			}
		}
	}
	return out;
}

const contentCount = computed(() =>
	flatten().filter((df) => !STRUCTURAL.has(df.fieldtype)).length
);

// ── Selection ──────────────────────────────────────────────────────────
function selectForm() { sel.type = "form"; sel.node = null; }
function selectField(w) { sel.type = "field"; sel.node = w; }
function selectContainer(kind, node) {
	if (!node.df) {
		node.df = makeBreak({ section: "Section Break", column: "Column Break", tab: "Tab Break" }[kind]);
	}
	sel.type = kind;
	sel.node = node;
}
function isSel(kind, node) { return sel.type === kind && sel.node === node; }
function isSelField(w) { return sel.type === "field" && sel.node === w; }

function tabLabel(tab, i) { return (tab.df && tab.df.label) || (i === 0 ? "Details" : `Tab ${i + 1}`); }
function sectionLabel(section) { return (section.df && section.df.label) || "Section"; }

function autoName(df) {
	if (!df.fieldname && df.label && !STRUCTURAL.has(df.fieldtype)) {
		df.fieldname = df.label.trim().toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "");
	}
}

// ── Add / remove ───────────────────────────────────────────────────────
function currentSection() {
	if (sel.type === "column" && sel.node) return findSectionOfColumn(sel.node);
	if (sel.type === "section" && sel.node) return sel.node;
	if (sel.type === "field" && sel.node) {
		const col = findColumnOfField(sel.node);
		if (col) return findSectionOfColumn(col);
	}
	const secs = activeTab.value.sections;
	return secs[secs.length - 1];
}
function currentColumn() {
	if (sel.type === "column" && sel.node) return sel.node;
	if (sel.type === "field" && sel.node) {
		const col = findColumnOfField(sel.node);
		if (col) return col;
	}
	const s = currentSection();
	return s.columns[s.columns.length - 1];
}
function findColumnOfField(w) {
	for (const s of activeTab.value.sections)
		for (const c of s.columns)
			if (c.fields.includes(w)) return c;
	return null;
}
function findSectionOfColumn(col) {
	for (const s of activeTab.value.sections)
		if (s.columns.includes(col)) return s;
	return null;
}

function addFieldToColumn(col) {
	const w = wrapField(normalizeDf({ fieldtype: "Data", label: "", fieldname: "" }));
	col.fields.push(w);
	selectField(w);
}
function addField() { addFieldToColumn(currentColumn()); }
function addSection() {
	const s = wrapSection(makeBreak("Section Break"));
	s.columns.push(wrapColumn(null));
	activeTab.value.sections.push(s);
	selectContainer("section", s);
}
function addColumn(section) {
	const sec = section && section.columns ? section : currentSection();
	const c = wrapColumn(makeBreak("Column Break"));
	sec.columns.push(c);
	selectContainer("column", c);
}
function addTab() {
	const t = wrapTab(makeBreak("Tab Break"));
	const s = wrapSection(null);
	s.columns.push(wrapColumn(null));
	t.sections.push(s);
	tabs.value.push(t);
	activeTabIndex.value = tabs.value.length - 1;
	selectContainer("tab", t);
}

function removeField(column, w) {
	const i = column.fields.indexOf(w);
	if (i >= 0) column.fields.splice(i, 1);
	if (sel.node === w) selectForm();
}
function deleteSelected() {
	if (sel.type === "field" && sel.node) {
		const col = findColumnOfField(sel.node);
		if (col) removeField(col, sel.node);
		return;
	}
	if (sel.type === "section" && sel.node) {
		const secs = activeTab.value.sections;
		const i = secs.indexOf(sel.node);
		if (i >= 0) secs.splice(i, 1);
	} else if (sel.type === "column" && sel.node) {
		const s = findSectionOfColumn(sel.node);
		if (s) {
			const i = s.columns.indexOf(sel.node);
			if (i >= 0) s.columns.splice(i, 1);
		}
	} else if (sel.type === "tab" && sel.node) {
		const i = tabs.value.indexOf(sel.node);
		if (i >= 0) tabs.value.splice(i, 1);
		if (activeTabIndex.value >= tabs.value.length) activeTabIndex.value = Math.max(0, tabs.value.length - 1);
	}
	ensureStructure();
	selectForm();
}

// ── IR round-trip ──────────────────────────────────────────────────────
function loadIr(ir) {
	if (!ir) return;
	if (ir.doctype_name) dtName.value = ir.doctype_name;
	if (ir.module) dtModule.value = ir.module;
	dtAutoname.value = ir.autoname || "";
	isChild.value = !!ir.is_child_table;
	buildTree(ir.fields || []);
	selectForm();
	appliedName.value = "";
	applyError.value = "";
}

function currentIr() {
	return {
		doctype_name: dtName.value.trim(),
		module: dtModule.value || "ONE BPMN",
		is_child_table: isChild.value,
		autoname: dtAutoname.value || "",
		fields: flatten().map((f) => {
			const out = { ...f };  // preserve all properties, incl. ones the builder doesn't show
			const structural = STRUCTURAL.has(f.fieldtype);
			out.fieldname = structural ? "" : (f.fieldname || "").trim();
			out.label = f.label || "";
			out.options = (f.options || "").trim();
			for (const flag of FIELD_FLAGS) {
				if (flag in out) out[flag] = out[flag] ? 1 : 0;
			}
			return out;
		}),
	};
}

// ── API calls ──────────────────────────────────────────────────────────
async function loadSchema(dt) {
	try {
		const res = await frappeRequest({ url: `${API}get_doctype_schema`, params: { doctype: dt } });
		if (res?.exists && res.doctype_ir) loadIr(res.doctype_ir);
	} catch (e) { /* new doctype — nothing to load */ }
}

async function loadModules() {
	try {
		const res = await frappeRequest({ url: `${API}list_modules` });
		if (Array.isArray(res)) modules.value = res;
	} catch (e) { /* fall back to the current module only */ }
}

function chatHistoryPayload() {
	return messages.value
		.filter((m) => m.role === "user" || m.role === "assistant")
		.slice(-10)
		.map((m) => ({ role: m.role, content: m.content }));
}

function errText(e) {
	return e && (e.message || e._server_messages) ? String(e.message || e._server_messages) : "";
}

// A Docu turn runs a 25–50s multi-stage LLM pipeline. Rather than block one HTTP
// request that long (it times out → "Something went wrong"), we enqueue the turn
// on the backend and poll docu_chat_status until it finishes.
async function sendMessage(preset) {
	const text = (preset ?? inputText.value).trim();
	if (!text || isTyping.value) return;
	pushMsg("user", text);
	inputText.value = "";
	isTyping.value = true;
	try {
		const res = await frappeRequest({
			url: `${API}docu_chat_async`,
			method: "POST",
			params: {
				message: text,
				session_id: sessionId.value,
				conversation_name: conversationName.value || null,
				// chat_history is JSON-encoded (backend takes str) — matches ProsAlly;
				// process_context is sent as a raw object (backend takes dict) — matches Logix.
				chat_history: JSON.stringify(chatHistoryPayload()),
				doctype: dtName.value || props.doctype || "",
				target_module: dtModule.value || "",
				process_context: props.processContext || null,
			},
		});
		if (res?.conversation_name) conversationName.value = res.conversation_name;
		if (!res?.turn_id) throw new Error("Could not start the request.");
		pollTurn(res.turn_id);  // resolves the reply asynchronously; keeps the typing indicator up
	} catch (e) {
		pushMsg("assistant", errText(e) || "Something went wrong. Please try again.");
		isTyping.value = false;
	}
}

// Poll a backgrounded turn to completion. Cancellable (close/unmount).
function pollTurn(turnId) {
	const startedAt = Date.now();
	const MAX_MS = 180000;   // give up surfacing after 3 min (turn may still finish server-side)
	const INTERVAL = 1800;
	pollCancelled = false;

	const finish = (fn) => { if (pollCancelled) return; fn(); isTyping.value = false; };

	const tick = async () => {
		if (pollCancelled) return;
		try {
			const st = await frappeRequest({
				url: `${API}docu_chat_status`,
				params: { turn_id: turnId },
			});
			if (pollCancelled) return;

			if (st?.status === "done") {
				const r = st.result || {};
				return finish(() => {
					if (r.conversation_name) conversationName.value = r.conversation_name;
					pushMsg("assistant", r.response || "Sorry, I couldn't process that.", { options: r.options || null });
					if (r.doctype_ir) loadIr(r.doctype_ir);
				});
			}
			if (st?.status === "error") {
				return finish(() => pushMsg("assistant", `⚠️ ${st.error || "Something went wrong. Please try again."}`));
			}
			// 'unknown' right after start = worker hasn't written yet; only treat as lost after a grace period.
			if (st?.status === "unknown" && Date.now() - startedAt > 15000) {
				return finish(() => pushMsg("assistant", "I lost track of that request. Please try again."));
			}
			if (Date.now() - startedAt > MAX_MS) {
				return finish(() => pushMsg("assistant", "This is taking longer than usual — it may still finish. Please wait a moment or try again."));
			}
			pollTimer = setTimeout(tick, INTERVAL);
		} catch (e) {
			// transient network blip — keep polling until the ceiling
			if (Date.now() - startedAt > MAX_MS) {
				return finish(() => pushMsg("assistant", errText(e) || "Something went wrong. Please try again."));
			}
			pollTimer = setTimeout(tick, INTERVAL);
		}
	};
	tick();
}

function selectOption(opt) { sendMessage(opt); }

function onKeydown(e) {
	if (e.key === "Enter" && !e.shiftKey) {
		e.preventDefault();
		sendMessage();
	}
}

// Step 1: preview what Apply will do, then show a confirmation (#3/#4).
async function requestApply() {
	applyError.value = "";
	appliedName.value = "";
	previewing.value = true;
	try {
		const res = await frappeRequest({
			url: `${API}preview_doctype`,
			method: "POST",
			params: { ir: JSON.stringify(currentIr()) },
		});
		if (res && res.valid === false) {
			applyError.value = (res.violations || []).join(" ") || "The DocType has problems that must be fixed first.";
			return;
		}
		previewData.value = res;
		showConfirm.value = true;
	} catch (e) {
		applyError.value = errText(e) || "Could not check the DocType.";
	} finally {
		previewing.value = false;
	}
}

// Step 2: the user confirmed — apply for real (confirm=1 clears the data-loss guard).
async function confirmApply() {
	applying.value = true;
	try {
		const res = await frappeRequest({
			url: `${API}apply_doctype`,
			method: "POST",
			params: { ir: JSON.stringify(currentIr()), confirm: 1 },
		});
		const name = res?.name || dtName.value;
		appliedName.value = name;
		showConfirm.value = false;
		const verb = { created: "created", updated: "updated", fields_added: "updated", unchanged: "already up to date" }[res?.action] || "saved";
		emit("applied", name);
		const setNote = res?.action === "created" ? " and set it on this step" : "";
		const childNote = (res?.child_tables && res.child_tables.length)
			? ` (plus ${res.child_tables.length} linked list${res.child_tables.length === 1 ? "" : "s"})`
			: "";
		pushMsg("assistant", `✓ Done — I've **${verb}** the **${name}** doctype${childNote}${setNote}. [Open it](${res?.url || "#"})`);
	} catch (e) {
		applyError.value = errText(e) || "Could not apply the DocType.";
		showConfirm.value = false;
		pushMsg("assistant", `⚠️ I couldn't apply the DocType: ${applyError.value}`);
	} finally {
		applying.value = false;
	}
}

// ── Undo / redo (#12) ──────────────────────────────────────────────────
function recordSnapshot() {
	if (isRestoring) return;
	const snap = JSON.stringify(currentIr());
	if (history.value[histIndex.value] === snap) return;
	history.value = history.value.slice(0, histIndex.value + 1);
	history.value.push(snap);
	if (history.value.length > 60) history.value.shift();
	histIndex.value = history.value.length - 1;
}
function scheduleSnapshot() {
	if (isRestoring) return;
	if (snapTimer) clearTimeout(snapTimer);
	snapTimer = setTimeout(recordSnapshot, 400);
}
function restoreSnapshot(snap) {
	isRestoring = true;
	try { loadIr(JSON.parse(snap)); } catch (e) { /* ignore malformed snapshot */ }
	nextTick(() => { isRestoring = false; });
}
function undo() {
	if (!canUndo.value) return;
	if (snapTimer) { clearTimeout(snapTimer); recordSnapshot(); }  // flush pending edit first
	histIndex.value -= 1;
	restoreSnapshot(history.value[histIndex.value]);
}
function redo() {
	if (!canRedo.value) return;
	histIndex.value += 1;
	restoreSnapshot(history.value[histIndex.value]);
}
function onGlobalKeydown(e) {
	if (!(e.ctrlKey || e.metaKey)) return;
	const k = (e.key || "").toLowerCase();
	if (k === "z" && !e.shiftKey) { e.preventDefault(); undo(); }
	else if ((k === "z" && e.shiftKey) || k === "y") { e.preventDefault(); redo(); }
}

// ── Templates (#12) ────────────────────────────────────────────────────
function pickTemplate(t) {
	loadIr(JSON.parse(JSON.stringify(t.ir)));
	showTemplates.value = false;
	scheduleSnapshot();
}

function stopPolling() {
	pollCancelled = true;
	if (pollTimer) { clearTimeout(pollTimer); pollTimer = null; }
	if (snapTimer) { clearTimeout(snapTimer); snapTimer = null; }
	window.removeEventListener("keydown", onGlobalKeydown, true);
}

function close() {
	stopPolling();
	// Hand control to the process map's close branch (Cleanup → Conversation Ended).
	if (conversationName.value) {
		frappeRequest({
			url: "/api/method/one_bpmn.api.server_script_api.end_chat_conversation",
			method: "POST",
			params: { conversation_name: conversationName.value },
		}).catch(() => {});
	}
	emit("close");
}

onBeforeUnmount(stopPolling);

// ── Init ──────────────────────────────────────────────────────────────
onMounted(async () => {
	buildTree([]);  // start with an empty tab/section/column so the canvas is usable
	selectForm();
	loadModules();  // populate the module picker (fire-and-forget)
	if (props.doctype) {
		// A doctype is already selected on the shape — load its form builder view
		// and greet with a change-focused message.
		await loadSchema(props.doctype);
		const dt = props.doctype;
		pushMsg(
			"assistant",
			`Hello, I am **Docu**.\n` +
			`Happy to help with changes to **${dt}** doctype.\n` +
			`How would you like me to assist in redefining the **${dt}** doctype or its fields?`,
		);
	} else {
		// No doctype selected on the shape — greet with a create-focused message.
		pushMsg(
			"assistant",
			`Hello, I am **Docu**.\n` +
			`Happy to help with creating doctypes.\n` +
			`If the doctype already exists and you just want to make changes, please close this window, ` +
			`select the doctype in the relevant shape's property panel and click on the "Launch Docu" button again.`,
		);
	}
	nextTick(() => inputEl.value?.focus());

	// Undo/redo: seed the baseline snapshot, then record on every edit.
	nextTick(() => {
		recordSnapshot();
		watch([tabs, dtName, dtModule, dtAutoname, isChild], scheduleSnapshot, { deep: true });
	});
	window.addEventListener("keydown", onGlobalKeydown, true);
});
</script>

<style scoped>
/* ══════════════════════════════════════════════════════════════════════
   Material Design 3 token layer (light scheme, indigo primary).
   Color roles, elevation, shape and motion — everything below references
   these so the whole panel reads as one system.
   ══════════════════════════════════════════════════════════════════════ */
.dc-overlay {
	--md-primary: #4f46e5;
	--md-on-primary: #ffffff;
	--md-primary-container: #e0e7ff;
	--md-on-primary-container: #26235f;
	--md-secondary-container: #e3e2f4;
	--md-on-secondary-container: #3b3a56;
	--md-surface: #fdfcff;
	--md-surface-container-lowest: #ffffff;
	--md-surface-container-low: #f6f5fc;
	--md-surface-container: #f1f0f8;
	--md-surface-container-high: #ebeaf3;
	--md-surface-container-highest: #e5e4ee;
	--md-surface-variant: #e5e1ec;
	--md-on-surface: #1b1b21;
	--md-on-surface-variant: #47464f;
	--md-outline: #77767f;
	--md-outline-variant: #c8c5d0;
	--md-error: #ba1a1a;
	--md-on-error: #ffffff;
	--md-error-container: #ffdad6;
	--md-on-error-container: #410002;
	--md-success: #106b34;
	/* state-layer opacities */
	--md-state-hover: 0.08;
	--md-state-focus: 0.12;
	/* elevation */
	--md-elev-1: 0 1px 2px rgba(0,0,0,.28), 0 1px 3px 1px rgba(0,0,0,.14);
	--md-elev-2: 0 1px 2px rgba(0,0,0,.28), 0 2px 6px 2px rgba(0,0,0,.14);
	--md-elev-3: 0 4px 8px 3px rgba(0,0,0,.14), 0 1px 3px rgba(0,0,0,.28);
	/* shape */
	--md-corner-xs: 4px; --md-corner-sm: 8px; --md-corner-md: 12px;
	--md-corner-lg: 16px; --md-corner-xl: 28px; --md-corner-full: 999px;
	/* motion */
	--md-ease: cubic-bezier(0.2, 0, 0, 1);
	--md-dur: 180ms;

	position: fixed; inset: 0; z-index: 2000;
	background: rgba(20, 18, 30, 0.45);
	display: flex; align-items: center; justify-content: center;
	font-family: "Inter", "Roboto", system-ui, -apple-system, sans-serif;
	animation: dc-scrim-in var(--md-dur) var(--md-ease);
}
@keyframes dc-scrim-in { from { opacity: 0; } to { opacity: 1; } }

.dc-window {
	position: relative;
	width: min(1640px, 98vw); height: min(960px, 96vh);
	background: var(--md-surface-container-low);
	color: var(--md-on-surface);
	border-radius: var(--md-corner-xl); overflow: hidden;
	display: flex; flex-direction: column;
	box-shadow: var(--md-elev-3);
	animation: dc-window-in 220ms var(--md-ease);
}
@keyframes dc-window-in { from { opacity: 0; transform: scale(.96) translateY(8px); } to { opacity: 1; transform: none; } }

/* ── Header (top app bar) ── */
.dc-window-header {
	display: flex; align-items: center; justify-content: space-between;
	padding: 12px 16px 12px 20px; background: var(--md-surface-container);
}
.dc-window-title { display: flex; align-items: center; gap: 10px; }
.dc-badge { background: var(--md-primary); color: var(--md-on-primary); font-weight: 600; font-size: 12px; letter-spacing: .03em; padding: 4px 10px; border-radius: var(--md-corner-sm); }
.dc-subtitle { font-size: 16px; line-height: 24px; color: var(--md-on-surface); font-weight: 500; }
.dc-dt-chip { font-size: 12px; color: var(--md-on-primary-container); background: var(--md-primary-container); padding: 4px 10px; border-radius: var(--md-corner-sm); max-width: 260px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
/* MD3 icon button — circular 40dp target with a hover state layer */
.dc-icon-btn { position: relative; border: none; background: transparent; font-size: 18px; cursor: pointer; color: var(--md-on-surface-variant); width: 40px; height: 40px; border-radius: var(--md-corner-full); display: flex; align-items: center; justify-content: center; transition: background-color var(--md-dur) var(--md-ease); }
.dc-icon-btn:hover { background: rgba(71,70,79,var(--md-state-hover)); }
.dc-icon-btn:active { background: rgba(71,70,79,var(--md-state-focus)); }

.dc-root { flex: 1; display: flex; min-height: 0; }

/* ── Chat (left) ── */
.dc-chat-panel { width: 460px; flex: none; display: flex; flex-direction: column; background: var(--md-surface-container-low); border-right: 1px solid var(--md-outline-variant); min-width: 0; }
.dc-messages { flex: 1; overflow-y: auto; padding: 16px; display: flex; flex-direction: column; gap: 12px; }
.dc-msg-row { display: flex; }
.dc-msg-row.user { justify-content: flex-end; }
.dc-msg-body { max-width: 90%; }
.dc-bubble-user { background: var(--md-primary); color: var(--md-on-primary); padding: 10px 14px; border-radius: var(--md-corner-lg) var(--md-corner-lg) var(--md-corner-xs) var(--md-corner-lg); font-size: 14px; line-height: 20px; }
.dc-bubble-bot { background: var(--md-surface-container-high); color: var(--md-on-surface); padding: 10px 14px; border-radius: var(--md-corner-lg) var(--md-corner-lg) var(--md-corner-lg) var(--md-corner-xs); font-size: 14px; line-height: 20px; }
.dc-bubble-bot :deep(p) { margin: 0 0 6px; } .dc-bubble-bot :deep(p:last-child) { margin: 0; }
.dc-bubble-bot :deep(a) { color: var(--md-primary); }
.dc-msg-time { font-size: 11px; color: var(--md-on-surface-variant); margin-top: 4px; }
.dc-msg-row.user .dc-msg-time { text-align: right; }
/* assist chips (suggested replies) */
.dc-options { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 8px; }
.dc-option-btn { border: 1px solid var(--md-outline-variant); background: transparent; color: var(--md-primary); border-radius: var(--md-corner-sm); padding: 6px 14px; font-size: 13px; font-weight: 500; cursor: pointer; transition: background-color var(--md-dur) var(--md-ease); }
.dc-option-btn:hover { background: rgba(79,70,229,var(--md-state-hover)); }
.dc-typing span { display: inline-block; width: 6px; height: 6px; margin: 0 1px; background: var(--md-on-surface-variant); border-radius: 50%; animation: dc-blink 1.2s infinite; }
.dc-typing span:nth-child(2) { animation-delay: .2s; } .dc-typing span:nth-child(3) { animation-delay: .4s; }
@keyframes dc-blink { 0%, 60%, 100% { opacity: .3; } 30% { opacity: 1; } }
.dc-input-area { display: flex; gap: 10px; align-items: flex-end; padding: 12px; border-top: 1px solid var(--md-outline-variant); }
.dc-input { flex: 1; resize: none; border: 1px solid var(--md-outline); border-radius: var(--md-corner-lg); padding: 10px 14px; font-size: 14px; line-height: 20px; font-family: inherit; background: var(--md-surface-container-low); color: var(--md-on-surface); transition: border-color var(--md-dur) var(--md-ease), box-shadow var(--md-dur) var(--md-ease); }
.dc-input:focus { outline: none; border-color: var(--md-primary); box-shadow: inset 0 0 0 1px var(--md-primary); }
/* filled tonal FAB-style send */
.dc-send-btn { border: none; background: var(--md-primary); color: var(--md-on-primary); border-radius: var(--md-corner-lg); width: 48px; height: 44px; cursor: pointer; font-size: 16px; box-shadow: var(--md-elev-1); transition: box-shadow var(--md-dur) var(--md-ease), background-color var(--md-dur) var(--md-ease); }
.dc-send-btn:hover:not(:disabled) { box-shadow: var(--md-elev-2); }
.dc-send-btn:disabled { background: rgba(27,27,33,0.12); color: rgba(27,27,33,0.38); box-shadow: none; cursor: not-allowed; }

/* ── Builder canvas (middle) ── */
.dc-builder-panel { flex: 1; display: flex; flex-direction: column; min-width: 0; background: var(--md-surface-container); }
.dc-builder-topbar { display: flex; align-items: center; gap: 12px; padding: 12px 16px; background: var(--md-surface-container-low); border-bottom: 1px solid var(--md-outline-variant); }
.dc-form-name { flex: 1; min-width: 0; }
.dc-name-input { width: 100%; border: 1px solid var(--md-outline); border-radius: var(--md-corner-sm); padding: 9px 12px; font-size: 15px; font-weight: 500; background: var(--md-surface-container-lowest); color: var(--md-on-surface); transition: border-color var(--md-dur) var(--md-ease), box-shadow var(--md-dur) var(--md-ease); }
.dc-name-input:focus { outline: none; border-color: var(--md-primary); box-shadow: inset 0 0 0 1px var(--md-primary); }
.dc-add-group { display: flex; gap: 8px; align-items: center; }
/* MD3 tonal buttons */
.dc-add-btn { position: relative; border: none; background: var(--md-secondary-container); color: var(--md-on-secondary-container); border-radius: var(--md-corner-full); padding: 8px 16px; font-size: 13px; font-weight: 500; cursor: pointer; white-space: nowrap; transition: background-color var(--md-dur) var(--md-ease), box-shadow var(--md-dur) var(--md-ease); }
.dc-add-btn:hover { box-shadow: var(--md-elev-1); background: color-mix(in srgb, var(--md-on-secondary-container) 8%, var(--md-secondary-container)); }
.dc-gear-btn { position: relative; border: none; background: transparent; color: var(--md-on-surface-variant); border-radius: var(--md-corner-full); width: 40px; height: 40px; cursor: pointer; font-size: 16px; transition: background-color var(--md-dur) var(--md-ease); }
.dc-gear-btn:hover { background: rgba(71,70,79,var(--md-state-hover)); }
.dc-gear-btn.active { background: var(--md-primary-container); color: var(--md-on-primary-container); }

/* MD3 secondary tabs with sliding active indicator */
.dc-tabs { display: flex; gap: 2px; padding: 6px 14px 0; overflow-x: auto; background: var(--md-surface-container); }
.dc-tab { position: relative; display: flex; align-items: center; gap: 6px; background: transparent; color: var(--md-on-surface-variant); border: none; border-radius: var(--md-corner-sm) var(--md-corner-sm) 0 0; padding: 10px 16px 12px; font-size: 13px; font-weight: 500; cursor: pointer; white-space: nowrap; transition: background-color var(--md-dur) var(--md-ease), color var(--md-dur) var(--md-ease); }
.dc-tab:hover { background: rgba(71,70,79,var(--md-state-hover)); }
.dc-tab.active { color: var(--md-primary); }
.dc-tab.active::after { content: ""; position: absolute; left: 12px; right: 12px; bottom: 0; height: 3px; background: var(--md-primary); border-radius: 3px 3px 0 0; }
.dc-tab.sel { color: var(--md-primary); }
.dc-tab-edit { border: none; background: transparent; cursor: pointer; color: inherit; opacity: .6; font-size: 12px; }
.dc-tab-edit:hover { opacity: 1; }

.dc-canvas { flex: 1; overflow-y: auto; padding: 16px; }
.dc-sections { display: flex; flex-direction: column; gap: 14px; }
/* elevated cards */
.dc-section { background: var(--md-surface-container-lowest); border: 1px solid transparent; border-radius: var(--md-corner-md); padding: 12px 14px; box-shadow: var(--md-elev-1); transition: box-shadow var(--md-dur) var(--md-ease), border-color var(--md-dur) var(--md-ease); }
.dc-section.sel { border-color: var(--md-primary); box-shadow: 0 0 0 1px var(--md-primary), var(--md-elev-1); }
.dc-section-bar { display: flex; align-items: center; gap: 8px; margin-bottom: 10px; }
.dc-section-grip { cursor: grab; color: var(--md-outline); font-size: 15px; line-height: 1; }
.dc-section-title { flex: 1; font-size: 14px; font-weight: 600; color: var(--md-on-surface); cursor: pointer; }
.dc-section-title:hover { color: var(--md-primary); }
/* text button */
.dc-mini-btn { border: none; background: transparent; color: var(--md-primary); border-radius: var(--md-corner-full); padding: 6px 12px; font-size: 13px; font-weight: 500; cursor: pointer; transition: background-color var(--md-dur) var(--md-ease); }
.dc-mini-btn:hover { background: rgba(79,70,229,var(--md-state-hover)); }

.dc-columns { display: flex; gap: 12px; align-items: flex-start; }
.dc-column { flex: 1; min-width: 0; min-height: 64px; border: 1px dashed var(--md-outline-variant); border-radius: var(--md-corner-md); padding: 10px; background: var(--md-surface); transition: border-color var(--md-dur) var(--md-ease), background-color var(--md-dur) var(--md-ease); }
.dc-column.sel { border-style: solid; border-color: var(--md-primary); background: color-mix(in srgb, var(--md-primary) 4%, var(--md-surface)); }
.dc-col-fields { display: flex; flex-direction: column; gap: 8px; min-height: 28px; }

/* field = filled card / list item with state layer */
.dc-chip { display: flex; align-items: center; gap: 8px; background: var(--md-surface-container-high); border: 1px solid transparent; border-radius: var(--md-corner-sm); padding: 8px 10px; cursor: pointer; transition: background-color var(--md-dur) var(--md-ease), border-color var(--md-dur) var(--md-ease); }
.dc-chip:hover { background: color-mix(in srgb, var(--md-on-surface) 6%, var(--md-surface-container-high)); }
.dc-chip.sel { border-color: var(--md-primary); background: var(--md-primary-container); }
.dc-chip-grip { cursor: grab; color: var(--md-outline); font-size: 13px; }
.dc-chip-main { flex: 1; min-width: 0; display: flex; flex-direction: column; }
.dc-chip-label { font-size: 14px; color: var(--md-on-surface); font-weight: 500; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.dc-chip-type { font-size: 11px; color: var(--md-on-surface-variant); text-transform: uppercase; letter-spacing: .04em; }
.dc-req { color: var(--md-error); font-weight: 700; }
.dc-chip-x { border: none; background: transparent; color: var(--md-on-surface-variant); cursor: pointer; font-size: 12px; border-radius: var(--md-corner-full); width: 24px; height: 24px; transition: background-color var(--md-dur) var(--md-ease), color var(--md-dur) var(--md-ease); }
.dc-chip-x:hover { color: var(--md-error); background: rgba(186,26,26,var(--md-state-hover)); }
/* text buttons for adding */
.dc-add-inline { margin-top: 8px; width: 100%; border: none; background: transparent; color: var(--md-primary); border-radius: var(--md-corner-sm); padding: 7px; font-size: 13px; font-weight: 500; cursor: pointer; transition: background-color var(--md-dur) var(--md-ease); }
.dc-add-inline:hover { background: rgba(79,70,229,var(--md-state-hover)); }
/* outlined button */
.dc-add-section { margin-top: 14px; border: 1px solid var(--md-outline); background: transparent; color: var(--md-primary); border-radius: var(--md-corner-full); padding: 9px 18px; font-size: 13px; font-weight: 500; cursor: pointer; transition: background-color var(--md-dur) var(--md-ease); }
.dc-add-section:hover { background: rgba(79,70,229,var(--md-state-hover)); }

/* ── Properties (right) ── */
.dc-props-panel { width: 312px; flex: none; border-left: 1px solid var(--md-outline-variant); background: var(--md-surface-container-low); overflow-y: auto; padding: 18px 16px; }
.dc-props-head { font-size: 14px; font-weight: 600; letter-spacing: .01em; color: var(--md-on-surface); margin-bottom: 16px; }
.dc-prop { display: flex; flex-direction: column; gap: 5px; margin-bottom: 14px; }
.dc-prop label { font-size: 12px; color: var(--md-on-surface-variant); font-weight: 500; }
/* MD3 outlined text field */
.dc-prop-input { border: 1px solid var(--md-outline); border-radius: var(--md-corner-xs); padding: 10px 12px; font-size: 14px; font-family: inherit; background: var(--md-surface-container-lowest); color: var(--md-on-surface); transition: border-color var(--md-dur) var(--md-ease), box-shadow var(--md-dur) var(--md-ease); }
.dc-prop-input:hover { border-color: var(--md-on-surface); }
.dc-prop-input:focus { outline: none; border-color: var(--md-primary); box-shadow: inset 0 0 0 1px var(--md-primary); }
.dc-mono { font-family: ui-monospace, monospace; }
/* checkbox flags */
.dc-flags { display: grid; grid-template-columns: 1fr 1fr; gap: 4px 8px; margin: 8px 0 16px; }
.dc-flags label { display: flex; align-items: center; gap: 8px; font-size: 13px; color: var(--md-on-surface); padding: 6px 8px; border-radius: var(--md-corner-sm); cursor: pointer; transition: background-color var(--md-dur) var(--md-ease); }
.dc-flags label:hover { background: rgba(71,70,79,var(--md-state-hover)); }
.dc-flags input[type="checkbox"] { width: 18px; height: 18px; accent-color: var(--md-primary); cursor: pointer; }
/* MD3 switch */
.dc-switch { display: flex; align-items: center; gap: 12px; margin: 6px 0 16px; cursor: pointer; font-size: 13px; color: var(--md-on-surface); }
.dc-switch input { position: absolute; opacity: 0; width: 0; height: 0; }
.dc-switch-track { position: relative; flex: none; width: 52px; height: 32px; border-radius: var(--md-corner-full); background: var(--md-surface-container-highest); border: 2px solid var(--md-outline); transition: background-color var(--md-dur) var(--md-ease), border-color var(--md-dur) var(--md-ease); }
.dc-switch-thumb { position: absolute; top: 50%; left: 6px; width: 16px; height: 16px; border-radius: 50%; background: var(--md-outline); transform: translateY(-50%); transition: left var(--md-dur) var(--md-ease), width var(--md-dur) var(--md-ease), height var(--md-dur) var(--md-ease), background-color var(--md-dur) var(--md-ease); }
.dc-switch input:checked + .dc-switch-track { background: var(--md-primary); border-color: var(--md-primary); }
.dc-switch input:checked + .dc-switch-track .dc-switch-thumb { left: 26px; width: 24px; height: 24px; background: var(--md-on-primary); }
.dc-switch input:focus-visible + .dc-switch-track { box-shadow: 0 0 0 3px rgba(79,70,229,.25); }
.dc-switch-text { line-height: 1.4; }
.dc-hint { font-size: 12px; color: var(--md-on-surface-variant); line-height: 1.5; margin: 12px 0; }
/* error text button */
.dc-delete-btn { width: 100%; border: none; background: transparent; color: var(--md-error); border-radius: var(--md-corner-full); padding: 10px; font-size: 13px; font-weight: 500; cursor: pointer; transition: background-color var(--md-dur) var(--md-ease); }
.dc-delete-btn:hover { background: rgba(186,26,26,var(--md-state-hover)); }

/* ── Footer ── */
.dc-window-footer { display: flex; align-items: center; justify-content: flex-end; gap: 12px; padding: 12px 16px; background: var(--md-surface-container); }
.dc-error { color: var(--md-error); font-size: 13px; margin-right: auto; }
.dc-ok { color: var(--md-success); font-size: 13px; font-weight: 500; margin-right: auto; }
.dc-count { color: var(--md-on-surface-variant); font-size: 13px; margin-right: auto; }
/* MD3 filled button */
.dc-apply-btn { border: none; background: var(--md-primary); color: var(--md-on-primary); border-radius: var(--md-corner-full); padding: 11px 24px; font-size: 14px; font-weight: 500; cursor: pointer; box-shadow: var(--md-elev-1); transition: box-shadow var(--md-dur) var(--md-ease), background-color var(--md-dur) var(--md-ease); }
.dc-apply-btn:hover:not(:disabled) { box-shadow: var(--md-elev-2); background: color-mix(in srgb, var(--md-on-primary) 8%, var(--md-primary)); }
.dc-apply-btn:disabled { background: rgba(27,27,33,0.12); color: rgba(27,27,33,0.38); box-shadow: none; cursor: not-allowed; }

/* ── History group (undo/redo/templates) ── */
.dc-hist-group { display: flex; gap: 6px; align-items: center; }
.dc-icon-sm { border: none; background: transparent; color: var(--md-on-surface-variant); border-radius: var(--md-corner-full); width: 34px; height: 34px; font-size: 16px; cursor: pointer; transition: background-color var(--md-dur) var(--md-ease); }
.dc-icon-sm:hover:not(:disabled) { background: rgba(71,70,79,var(--md-state-hover)); }
.dc-icon-sm:disabled { opacity: .35; cursor: not-allowed; }

/* ── Modal (confirmation + templates) ── */
.dc-modal-scrim { position: absolute; inset: 0; z-index: 10; background: rgba(20,18,30,0.45); display: flex; align-items: center; justify-content: center; animation: dc-scrim-in var(--md-dur) var(--md-ease); }
.dc-modal { width: min(560px, 90%); max-height: 80%; overflow-y: auto; background: var(--md-surface-container-low); border-radius: var(--md-corner-lg); box-shadow: var(--md-elev-3); padding: 22px 24px; animation: dc-window-in 200ms var(--md-ease); }
.dc-modal-title { font-size: 18px; font-weight: 600; color: var(--md-on-surface); margin-bottom: 8px; }
.dc-modal-summary { font-size: 14px; line-height: 1.5; color: var(--md-on-surface-variant); margin: 0 0 14px; }
.dc-diff { display: flex; flex-direction: column; gap: 4px; margin-bottom: 12px; font-size: 13px; }
.dc-diff-line { padding: 6px 10px; border-radius: var(--md-corner-sm); }
.dc-diff-add { background: color-mix(in srgb, var(--md-success) 12%, transparent); color: var(--md-success); }
.dc-diff-chg { background: rgba(71,70,79,var(--md-state-hover)); color: var(--md-on-surface); }
.dc-diff-rem { background: var(--md-error-container); color: var(--md-on-error-container); }
.dc-warn { background: var(--md-error-container); color: var(--md-on-error-container); border-radius: var(--md-corner-sm); padding: 10px 12px; font-size: 13px; line-height: 1.5; margin-bottom: 14px; }
.dc-modal-actions { display: flex; justify-content: flex-end; gap: 10px; margin-top: 8px; }
.dc-btn-text { border: none; background: transparent; color: var(--md-primary); border-radius: var(--md-corner-full); padding: 10px 18px; font-size: 14px; font-weight: 500; cursor: pointer; transition: background-color var(--md-dur) var(--md-ease); }
.dc-btn-text:hover { background: rgba(79,70,229,var(--md-state-hover)); }
.dc-btn-filled { border: none; background: var(--md-primary); color: var(--md-on-primary); border-radius: var(--md-corner-full); padding: 10px 20px; font-size: 14px; font-weight: 500; cursor: pointer; box-shadow: var(--md-elev-1); transition: box-shadow var(--md-dur) var(--md-ease), background-color var(--md-dur) var(--md-ease); }
.dc-btn-filled:hover:not(:disabled) { box-shadow: var(--md-elev-2); }
.dc-btn-filled:disabled { background: rgba(27,27,33,0.12); color: rgba(27,27,33,0.38); box-shadow: none; cursor: not-allowed; }
.dc-btn-danger { background: var(--md-error); }
.dc-btn-danger:hover:not(:disabled) { background: color-mix(in srgb, #000 8%, var(--md-error)); }

/* ── Template picker ── */
.dc-template-list { display: flex; flex-direction: column; gap: 8px; margin-bottom: 6px; }
.dc-template-item { display: flex; flex-direction: column; align-items: flex-start; gap: 2px; text-align: left; border: 1px solid var(--md-outline-variant); background: var(--md-surface-container-lowest); border-radius: var(--md-corner-md); padding: 12px 14px; cursor: pointer; transition: background-color var(--md-dur) var(--md-ease), border-color var(--md-dur) var(--md-ease); }
.dc-template-item:hover { border-color: var(--md-primary); background: color-mix(in srgb, var(--md-primary) 5%, var(--md-surface-container-lowest)); }
.dc-template-name { font-size: 14px; font-weight: 600; color: var(--md-on-surface); }
.dc-template-desc { font-size: 12px; color: var(--md-on-surface-variant); }
</style>
