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
						<!-- Top-level view tabs (mirrors Frappe's Form / Settings) -->
						<div class="dc-view-tabs">
							<button class="dc-view-tab" :class="{ active: view === 'form' }" @click="view = 'form'">Form</button>
							<button class="dc-view-tab" :class="{ active: view === 'settings' }" @click="view = 'settings'">Settings</button>
						</div>

						<template v-if="view === 'form'">
						<div class="dc-builder-topbar">
							<div class="dc-form-name">
								<input v-model="dtName" class="dc-name-input" placeholder="DocType name (e.g. Vehicle Inspection)"
									@focus="selectForm()" />
							</div>
							<div class="dc-hist-group">
								<button class="dc-icon-sm" :disabled="!canUndo" @click="undo" title="Undo (Ctrl+Z)">↶</button>
								<button class="dc-icon-sm" :disabled="!canRedo" @click="redo" title="Redo (Ctrl+Shift+Z)">↷</button>
							</div>
						</div>

						<!-- Frappe-style form-builder canvas -->
						<div class="fb-form" v-if="activeTab">
							<!-- click-away layer for the section “…” menu -->
							<div v-if="openMenu" class="fb-menu-backdrop" @click="openMenu = null"></div>
							<!-- Tab header -->
							<div class="fb-tab-header">
								<draggable :list="tabs" item-key="id" class="fb-tabs" :animation="150">
									<template #item="{ element: tab, index }">
										<div
											class="fb-tab"
											:class="{ active: index === activeTabIndex }"
											@click="activeTabIndex = index"
											@dblclick="selectContainer('tab', tab)"
										>
											<span>{{ tabLabel(tab, index) }}</span>
											<button class="fb-tab-edit" @click.stop="selectContainer('tab', tab)" title="Tab properties">⚙</button>
											<button v-if="tabs.length > 1" class="fb-tab-x" @click.stop="removeTab(tab)" title="Remove tab">✕</button>
										</div>
									</template>
								</draggable>
								<div class="fb-tab-actions">
									<button class="fb-addtab" @click="addTab()" title="Add tab">+ Add tab</button>
								</div>
							</div>

							<!-- Sections -->
							<div class="fb-canvas">
								<draggable
									:list="activeTab.sections"
									item-key="id"
									group="fb-sections"
									handle=".fb-section-grip"
									:animation="200"
								>
									<template #item="{ element: section }">
										<div class="fb-section-container">
											<div
												class="fb-section"
												:class="{ selected: isSel('section', section) }"
												@click.self="selectContainer('section', section)"
											>
												<div class="fb-section-header" @click.stop="selectContainer('section', section)">
													<div class="fb-section-label">
														<span class="fb-section-grip" title="Drag to reorder">⠿</span>
														<span class="fb-section-title" :class="{ empty: !(section.df && section.df.label) }">{{ (section.df && section.df.label) || 'No Label' }}</span>
													</div>
													<div class="fb-menu-wrap">
														<button class="fb-menu-btn" @click.stop="toggleMenu(section)" title="Section options">⋯</button>
														<div v-if="openMenu === section" class="fb-menu" @click.stop>
															<div v-for="(g, gi) in sectionMenu(section)" :key="gi" class="fb-menu-group">
																<div class="fb-menu-title">{{ g.group }}</div>
																<button v-for="it in g.items" :key="it.label" class="fb-menu-item" @click.stop="it.onClick()">{{ it.label }}</button>
															</div>
														</div>
													</div>
												</div>
												<draggable
													:list="section.columns"
													item-key="id"
													group="fb-columns"
													class="fb-section-columns"
													:animation="200"
												>
													<template #item="{ element: column }">
														<div
															class="fb-column"
															:class="{ selected: isSel('column', column) }"
															@click.self="selectContainer('column', column)"
														>
															<draggable
																:list="column.fields"
																item-key="id"
																group="fb-fields"
																class="fb-column-container"
																:animation="200"
															>
																<template #item="{ element: fld }">
																	<div
																		class="fb-field"
																		:class="{ selected: isSelField(fld) }"
																		:title="fld.df.fieldname || fld.df.label"
																		@click.stop="selectField(fld)"
																	>
																		<div class="control frappe-control editable">
																			<div class="field-controls">
																				<div class="field-label">
																					<span class="fb-flabel" :class="{ empty: !fld.df.label }">
																						{{ fld.df.label || ('No Label (' + fld.df.fieldtype + ')') }}
																					</span>
																					<span class="reqd-asterisk" v-if="fld.df.reqd">*</span>
																				</div>
																				<div class="field-actions">
																					<button class="fb-icon" @click.stop="duplicateField(column, fld)" title="Duplicate">⧉</button>
																					<button class="fb-icon" @click.stop="removeField(column, fld)" title="Remove">✕</button>
																				</div>
																			</div>
																			<!-- live control preview, per field type -->
																			<label v-if="previewKind(fld.df.fieldtype) === 'check'" class="fb-check">
																				<input type="checkbox" disabled />
																			</label>
																			<select v-else-if="previewKind(fld.df.fieldtype) === 'select'" class="form-control" disabled>
																				<option>{{ (fld.df.options || '').split('\n')[0] || '' }}</option>
																			</select>
																			<textarea v-else-if="previewKind(fld.df.fieldtype) === 'textarea'" class="form-control" rows="2" readonly></textarea>
																			<div v-else-if="previewKind(fld.df.fieldtype) === 'table'" class="fb-table-preview">
																				▦ {{ fld.df.options || 'child table' }}
																			</div>
																			<div v-else-if="previewKind(fld.df.fieldtype) === 'heading'" class="fb-heading-preview">{{ fld.df.label }}</div>
																			<div v-else-if="previewKind(fld.df.fieldtype) === 'html'" class="fb-html-preview">HTML</div>
																			<input v-else class="form-control" type="text" readonly :placeholder="previewPlaceholder(fld.df)" />
																		</div>
																	</div>
																</template>
															</draggable>
															<div class="fb-add-field">
																<button class="fb-add-btn" @click.stop="addFieldToColumn(column)">+ Add field</button>
															</div>
														</div>
													</template>
												</draggable>
											</div>
										</div>
									</template>
								</draggable>
							</div>
						</div>
						</template>

						<!-- Settings view (mirrors Frappe's DocType Settings page) -->
						<div v-else class="dc-settings-page">
							<div class="dc-settings-card">
								<!-- Identity / naming -->
								<div class="dc-settings-section">
									<div class="dc-settings-grid">
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
											<label>Auto Name</label>
											<input v-model="dtAutoname" class="dc-prop-input dc-mono" placeholder="e.g. field:vehicle_no or format:VI-.#####" />
										</div>
										<div class="dc-prop">
											<label>Description</label>
											<textarea v-model="dtSettings.description" class="dc-prop-input" rows="2"></textarea>
										</div>
										<label class="fb-prop-check">
											<input type="checkbox" v-model="isChild" />
											<span>Is Child Table (lives inside another DocType)</span>
										</label>
									</div>
								</div>

								<!-- Grouped settings, matching Frappe's sections -->
								<div v-for="sec in settingsSections" :key="sec.title" class="dc-settings-section">
									<div class="dc-settings-title">{{ sec.title }}</div>
									<div class="dc-settings-grid">
										<template v-for="f in sec.fields" :key="f.key">
											<label v-if="f.type === 'check'" class="fb-prop-check">
												<input type="checkbox" v-model="dtSettings[f.key]" />
												<span>{{ f.label }}</span>
											</label>
											<div v-else class="dc-prop">
												<label>{{ f.label }}</label>
												<select v-if="f.type === 'select'" v-model="dtSettings[f.key]" class="dc-prop-input">
													<option v-for="o in f.options" :key="o" :value="o">{{ o || "—" }}</option>
												</select>
												<input v-else-if="f.type === 'int'" type="number" v-model.number="dtSettings[f.key]" class="dc-prop-input" placeholder="0" />
												<input v-else v-model="dtSettings[f.key]" class="dc-prop-input" :placeholder="f.placeholder || ''" />
											</div>
										</template>
									</div>
								</div>

								<p class="dc-hint">These settings apply to the whole DocType. Switch to the <strong>Form</strong> tab to design its fields.</p>
							</div>
						</div>
					</div>

					<!-- ── RIGHT: Properties sidebar ───────────────────── -->
					<div class="dc-props-panel" v-if="view === 'form'">

						<!-- Field properties (Frappe-style: searchable + scrollable) -->
						<template v-if="sel.type === 'field' && sel.node">
							<div class="fb-props-header">
								<div class="fb-props-search">
									<span class="fb-props-search-ico">⌕</span>
									<input v-model="propSearch" type="text" placeholder="Search properties..." />
									<button v-if="propSearch" class="fb-props-search-x" @click="propSearch = ''" title="Clear">✕</button>
								</div>
								<button class="fb-props-close" @click="selectForm()" title="Close properties">✕</button>
							</div>
							<div class="fb-props-body">
								<template v-for="p in visibleFieldProps" :key="p.key">
									<label v-if="p.type === 'check'" class="fb-prop-check">
										<input type="checkbox" v-model="sel.node.df[p.key]" />
										<span>{{ p.label }}</span>
									</label>
									<div v-else class="dc-prop">
										<label>{{ p.label }}</label>
										<select v-if="p.type === 'select'" v-model="sel.node.df[p.key]" class="dc-prop-input">
											<option v-for="o in p.options" :key="o" :value="o">{{ o }}</option>
										</select>
										<textarea
											v-else-if="p.type === 'textarea' || p.type === 'code'"
											v-model="sel.node.df[p.key]"
											class="dc-prop-input"
											:class="{ 'dc-mono': p.type === 'code' }"
											rows="3"
											:placeholder="p.placeholder || ''"
										></textarea>
										<input v-else-if="p.type === 'int'" type="number" v-model.number="sel.node.df[p.key]" class="dc-prop-input" :placeholder="p.placeholder || '0'" />
										<input
											v-else
											v-model="sel.node.df[p.key]"
											class="dc-prop-input"
											:class="{ 'dc-mono': p.mono }"
											:placeholder="p.placeholder || ''"
											@blur="p.key === 'label' && autoName(sel.node.df)"
										/>
										<p v-if="p.hint" class="fb-prop-hint">{{ p.hint }}</p>
									</div>
								</template>
								<p v-if="!visibleFieldProps.length" class="dc-hint">No properties match “{{ propSearch }}”.</p>
								<button class="dc-delete-btn" @click="deleteSelected()">Delete field</button>
							</div>
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

						<!-- Nothing selected -->
						<template v-else>
							<div class="dc-props-head">Properties</div>
							<p class="dc-hint">
								Select a field, section, column or tab to edit its properties.
								Ask Docu on the left to build or change the DocType, then drag to arrange.
								DocType-wide settings live in the <strong>Settings</strong> tab.
							</p>
						</template>
					</div>

				</div>

				<!-- Footer — changes auto-save to the system -->
				<div class="dc-window-footer">
					<span class="dc-count">{{ contentCount }} field{{ contentCount === 1 ? "" : "s" }}</span>
					<span class="dc-save-status" :class="'st-' + saveState">
						<template v-if="saveState === 'saving'">Saving…</template>
						<template v-else-if="saveState === 'saved'">✓ Saved{{ appliedName ? ' “' + appliedName + '”' : '' }}</template>
						<template v-else-if="saveState === 'error'">⚠ {{ saveError }}</template>
						<template v-else>Changes save automatically</template>
					</span>
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
// Field boolean flags coerced to 0/1 on the way to the backend. Every 'check'
// property surfaced in the field-properties panel must live here so it is a
// controlled boolean in the UI and serialises to 0/1 for Frappe.
const FIELD_FLAGS = [
	"reqd", "in_list_view", "unique", "read_only", "in_standard_filter",
	"hidden", "bold", "non_negative", "collapsible",
	"fetch_if_empty", "in_global_search", "in_preview", "allow_in_quick_entry",
	"translatable", "print_hide", "report_hide", "search_index",
	"ignore_user_permissions", "allow_on_submit",
	"set_only_once", "allow_bulk_edit", "remember_last_selected_value",
	"ignore_xss_filter", "in_filter", "no_copy", "print_hide_if_no_value",
	"hide_days", "hide_seconds", "is_virtual", "sort_options",
	"show_on_timeline", "make_attachment_public",
];

// Which control preview to render for a field type (mirrors Frappe's controls).
const _TEXTAREA_TYPES = new Set(["Text", "Small Text", "Long Text", "Text Editor", "Code", "Markdown Editor"]);
function previewKind(t) {
	if (t === "Check") return "check";
	if (t === "Select") return "select";
	if (t === "Table" || t === "Table MultiSelect") return "table";
	if (t === "Heading") return "heading";
	if (t === "HTML") return "html";
	if (_TEXTAREA_TYPES.has(t)) return "textarea";
	return "input";
}
function previewPlaceholder(df) {
	const t = df.fieldtype;
	if (t === "Link" || t === "Dynamic Link") return df.options || "";
	if (t === "Date") return "YYYY-MM-DD";
	if (t === "Datetime") return "YYYY-MM-DD HH:MM:SS";
	if (t === "Time") return "HH:MM:SS";
	if (t === "Currency" || t === "Float" || t === "Int" || t === "Percent") return "0";
	if (t === "Phone") return "+0 000 000 0000";
	if (t === "Attach" || t === "Attach Image") return "Attach a file…";
	if (t === "Color") return "Choose a color";
	return "";
}

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

// DocType-level settings (mirrors the DocType doctype's own settings; keys/
// coercion match tools.py DOCTYPE_SETTING_* and docu_api._apply_doctype_settings).
const SETTING_FLAG_KEYS = [
	"is_submittable", "issingle", "editable_grid", "quick_entry", "track_changes",
	"track_seen", "track_views", "beta", "hide_toolbar", "allow_copy", "allow_rename",
	"allow_import", "allow_events_in_timeline", "allow_auto_repeat", "show_preview_popup",
	"show_name_in_global_search", "show_title_field_in_link", "translated_doctype",
	"make_attachments_public", "is_tree",
];
const SETTING_INT_KEYS = ["max_attachments"];
const SETTING_STR_KEYS = [
	"description", "image_field", "title_field", "search_fields",
	"default_print_format", "sort_field", "sort_order", "document_type",
];
function defaultSettings() {
	const s = {};
	for (const k of SETTING_FLAG_KEYS) s[k] = false;
	for (const k of SETTING_INT_KEYS) s[k] = 0;
	for (const k of SETTING_STR_KEYS) s[k] = "";
	s.editable_grid = true;   // Frappe's default for child tables
	s.sort_order = "DESC";
	return s;
}
const dtSettings = reactive(defaultSettings());
// Always include the current module (e.g. an agent-supplied one) so it stays selectable.
const moduleOptions = computed(() => {
	const list = modules.value.slice();
	for (const m of [dtModule.value, "ONE BPMN"]) {
		if (m && !list.includes(m)) list.unshift(m);
	}
	return list;
});

// Top-level builder view — mirrors Frappe's Form / Settings tabs.
const view = ref("form");            // 'form' | 'settings'
// Which section's "…" options menu is open (Frappe's section Dropdown).
const openMenu = ref(null);

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

// Auto-save: changes persist to the system automatically (no "Apply" button).
const saveState  = ref("idle");   // idle | saving | saved | error
const saveError  = ref("");
let autosaveTimer = null;
let autosaveInFlight = false;
let autosaveQueued = false;

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
function optionsHint(t) {
	if (t === "Link" || t === "Table" || t === "Table MultiSelect") return "Target DocType";
	if (t === "Dynamic Link") return "fieldname holding DocType";
	if (t === "Select") return "one choice per line";
	return "—";
}

// ── Field-properties panel (mirrors Frappe's searchable FieldProperties) ──
const propSearch = ref("");
const _NUMBER_TYPES = new Set(["Int", "Float", "Currency", "Percent"]);
const _NON_NEG_TYPES = new Set(["Int", "Float", "Currency"]);
const _LENGTH_TYPES = new Set(["Data", "Link", "Dynamic Link", "Password", "Select", "Read Only", "Attach", "Attach Image", "Int"]);
const _GLOBAL_SEARCH_TYPES = new Set(["Data", "Select", "Table", "Text", "Text Editor", "Link", "Small Text", "Long Text", "Read Only", "Heading", "Dynamic Link"]);
const _TRANSLATABLE_TYPES = new Set(["Data", "Select", "Text", "Small Text", "Text Editor"]);
const _NO_FETCH_TYPES = new Set(["HTML", "Heading", "Table", "Table MultiSelect"]);
const _PRECISION_OPTS = ["", "0", "1", "2", "3", "4", "5", "6", "7", "8", "9"];

// The full property list Frappe's DocField exposes (order, control type, labels,
// and per-fieldtype visibility mirror frappe/core/doctype/docfield). Layout-only
// props (collapsible, hide_border, show_dashboard…) are omitted since this panel
// only ever edits a real field inside a column.
function fieldPropDefs(df) {
	const t = df.fieldtype;
	return [
		{ key: "label", label: "Label", type: "data" },
		{ key: "fieldtype", label: "Type", type: "select", options: CONTENT_TYPES },
		{ key: "fieldname", label: "Name", type: "data", mono: true, placeholder: "snake_case" },
		{ key: "reqd", label: "Mandatory", type: "check", show: t !== "Check" && t !== "HTML" },
		{ key: "precision", label: "Precision", type: "select", options: _PRECISION_OPTS, show: t === "Float" || t === "Currency" || t === "Percent", hint: "Set non-standard precision for a Float or Currency field." },
		{ key: "length", label: "Length", type: "int", show: _LENGTH_TYPES.has(t) },
		{ key: "search_index", label: "Index", type: "check" },
		{ key: "in_list_view", label: "In List View", type: "check", show: !df.is_virtual },
		{ key: "in_standard_filter", label: "In List Filter", type: "check" },
		{ key: "in_global_search", label: "In Global Search", type: "check", show: _GLOBAL_SEARCH_TYPES.has(t) },
		{ key: "in_preview", label: "In Preview", type: "check", show: t !== "Table" && t !== "Table MultiSelect" },
		{ key: "allow_in_quick_entry", label: "Allow in Quick Entry", type: "check" },
		{ key: "bold", label: "Bold", type: "check" },
		{ key: "translatable", label: "Translatable", type: "check", show: _TRANSLATABLE_TYPES.has(t) },
		{ key: "options", label: "Options", type: "textarea", placeholder: optionsHint(t),
			hint: "For Links, enter the DocType as range. For Select, enter list of Options, each on a new line." },
		{ key: "default", label: "Default", type: "textarea" },
		{ key: "fetch_from", label: "Fetch From", type: "textarea", mono: true, show: !_NO_FETCH_TYPES.has(t), placeholder: "link_field.source_field" },
		{ key: "fetch_if_empty", label: "Fetch on Save if Empty", type: "check", show: !_NO_FETCH_TYPES.has(t), hint: "If unchecked, the value will always be re-fetched on save." },
		{ key: "depends_on", label: "Display Depends On (JS)", type: "code", mono: true, placeholder: "eval:doc.status=='Open'" },
		{ key: "hidden", label: "Hidden", type: "check" },
		{ key: "read_only", label: "Read Only", type: "check" },
		{ key: "unique", label: "Unique", type: "check" },
		{ key: "set_only_once", label: "Set only once", type: "check" },
		{ key: "allow_bulk_edit", label: "Allow Bulk Edit", type: "check", show: t === "Table" },
		{ key: "permlevel", label: "Perm Level", type: "int" },
		{ key: "ignore_user_permissions", label: "Ignore User Permissions", type: "check" },
		{ key: "allow_on_submit", label: "Allow on Submit", type: "check" },
		{ key: "report_hide", label: "Report Hide", type: "check" },
		{ key: "remember_last_selected_value", label: "Remember Last Selected Value", type: "check", show: t === "Link" },
		{ key: "ignore_xss_filter", label: "Ignore XSS Filter", type: "check", hint: "Don't encode HTML tags like <script> or just characters like < or >, as they could be intentionally used in this field." },
		{ key: "in_filter", label: "In Filter", type: "check" },
		{ key: "no_copy", label: "No Copy", type: "check" },
		{ key: "print_hide", label: "Print Hide", type: "check" },
		{ key: "print_hide_if_no_value", label: "Print Hide If No Value", type: "check", show: _NUMBER_TYPES.has(t) },
		{ key: "print_width", label: "Print Width", type: "data" },
		{ key: "width", label: "Width", type: "data" },
		{ key: "columns", label: "Columns", type: "int", hint: "Number of columns for a field in a List View or a Grid (Total Columns should be less than 11)." },
		{ key: "description", label: "Description", type: "textarea" },
		{ key: "mandatory_depends_on", label: "Mandatory Depends On (JS)", type: "code", mono: true, placeholder: "eval:doc.status=='Open'" },
		{ key: "read_only_depends_on", label: "Read Only Depends On (JS)", type: "code", mono: true, placeholder: "eval:doc.docstatus==1" },
		{ key: "hide_days", label: "Hide Days", type: "check", show: t === "Duration" },
		{ key: "hide_seconds", label: "Hide Seconds", type: "check", show: t === "Duration" },
		{ key: "non_negative", label: "Non Negative", type: "check", show: _NON_NEG_TYPES.has(t) },
		{ key: "max_height", label: "Max Height", type: "data" },
		{ key: "is_virtual", label: "Virtual", type: "check" },
		{ key: "documentation_url", label: "Documentation URL", type: "data", show: t !== "HTML" },
		{ key: "sort_options", label: "Sort Options", type: "check", show: t === "Select" },
		{ key: "show_on_timeline", label: "Show on Timeline", type: "check", show: !!df.hidden },
		{ key: "placeholder", label: "Placeholder", type: "data" },
		{ key: "make_attachment_public", label: "Make Attachment Public (by default)", type: "check", show: t === "Attach" || t === "Attach Image" },
	];
}
const visibleFieldProps = computed(() => {
	if (sel.type !== "field" || !sel.node) return [];
	const q = propSearch.value.trim().toLowerCase();
	return fieldPropDefs(sel.node.df).filter((p) => {
		if (p.show === false) return false;
		if (q && !(p.label.toLowerCase().includes(q) || p.key.toLowerCase().includes(q))) return false;
		return true;
	});
});

// ── DocType settings layout (mirrors the DocType doctype's Settings sections) ──
const settingsSections = computed(() => {
	const child = isChild.value;
	const sections = [
		{ title: "General", fields: [
			{ key: "is_submittable", label: "Is Submittable", type: "check", show: !child },
			{ key: "issingle", label: "Is Single", type: "check", show: !child },
			{ key: "editable_grid", label: "Editable Grid", type: "check", show: child },
			{ key: "quick_entry", label: "Quick Entry", type: "check", show: !child },
			{ key: "track_changes", label: "Track Changes", type: "check", show: !child },
			{ key: "track_seen", label: "Track Seen", type: "check", show: !child },
			{ key: "track_views", label: "Track Views", type: "check", show: !child },
			{ key: "beta", label: "Beta", type: "check", show: !child },
		] },
		{ title: "Form Settings", show: !child, fields: [
			{ key: "image_field", label: "Image Field", type: "data", placeholder: "an Attach Image fieldname" },
			{ key: "max_attachments", label: "Max Attachments", type: "int" },
			{ key: "hide_toolbar", label: "Hide Sidebar, Menu, and Comments", type: "check" },
			{ key: "allow_copy", label: "Hide Copy", type: "check" },
			{ key: "allow_rename", label: "Allow Rename", type: "check" },
			{ key: "allow_import", label: "Allow Import (via Data Import Tool)", type: "check" },
			{ key: "allow_events_in_timeline", label: "Allow events in timeline", type: "check" },
			{ key: "allow_auto_repeat", label: "Allow Auto Repeat", type: "check" },
		] },
		{ title: "View Settings", show: !child, fields: [
			{ key: "title_field", label: "Title Field", type: "data", placeholder: "a fieldname" },
			{ key: "search_fields", label: "Search Fields", type: "data", placeholder: "comma-separated fieldnames" },
			{ key: "sort_field", label: "Default Sort Field", type: "data", placeholder: "e.g. modified" },
			{ key: "sort_order", label: "Default Sort Order", type: "select", options: ["ASC", "DESC"] },
			{ key: "default_print_format", label: "Default Print Format", type: "data" },
			{ key: "document_type", label: "Show in Module Section", type: "select", options: ["", "Document", "Setup", "System", "Other"] },
			{ key: "show_preview_popup", label: "Show Preview Popup", type: "check" },
			{ key: "show_name_in_global_search", label: 'Make "name" searchable in Global Search', type: "check" },
			{ key: "show_title_field_in_link", label: "Show Title in Link Fields", type: "check" },
			{ key: "translated_doctype", label: "Translate Link Fields", type: "check" },
			{ key: "make_attachments_public", label: "Make Attachments Public by Default", type: "check" },
		] },
		{ title: "Advanced", fields: [
			{ key: "is_tree", label: "Is Tree", type: "check", show: !child },
		] },
	];
	return sections
		.filter((s) => s.show !== false)
		.map((s) => ({ ...s, fields: s.fields.filter((f) => f.show !== false) }))
		.filter((s) => s.fields.length);
});

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

function autoName(df) {
	if (!df.fieldname && df.label && !STRUCTURAL.has(df.fieldtype)) {
		df.fieldname = df.label.trim().toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "");
	}
}

// ── Add / remove ───────────────────────────────────────────────────────
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
function addTab() {
	const t = wrapTab(makeBreak("Tab Break"));
	const s = wrapSection(null);
	s.columns.push(wrapColumn(null));
	t.sections.push(s);
	tabs.value.push(t);
	activeTabIndex.value = tabs.value.length - 1;
	selectContainer("tab", t);
}
function removeTab(tab) {
	if (tabs.value.length <= 1) return;   // always keep at least one tab
	const i = tabs.value.indexOf(tab);
	if (i < 0) return;
	tabs.value.splice(i, 1);
	if (activeTabIndex.value >= tabs.value.length) activeTabIndex.value = tabs.value.length - 1;
	ensureStructure();
	selectForm();
}

// ── Section "…" options menu (mirrors Frappe's Section Dropdown) ─────────
function toggleMenu(section) { openMenu.value = openMenu.value === section ? null : section; }
function sectionIndex(section) { return activeTab.value.sections.indexOf(section); }

function addSectionBelow(section) {
	const s = wrapSection(makeBreak("Section Break"));
	s.columns.push(wrapColumn(null));
	const i = sectionIndex(section);
	activeTab.value.sections.splice(i + 1, 0, s);
	openMenu.value = null;
	selectContainer("section", s);
}
function removeSection(section) {
	const secs = activeTab.value.sections;
	const i = secs.indexOf(section);
	if (i >= 0) secs.splice(i, 1);
	openMenu.value = null;
	ensureStructure();
	selectForm();
}
function addColumnTo(section) {
	const c = wrapColumn(makeBreak("Column Break"));
	section.columns.push(c);
	openMenu.value = null;
	selectContainer("column", c);
}
function removeColumn(section) {
	// Remove the last column, moving its fields into the previous one (Frappe's behaviour).
	const cols = section.columns;
	if (cols.length <= 1) return;
	const last = cols[cols.length - 1];
	const prev = cols[cols.length - 2];
	prev.fields.push(...last.fields);
	cols.splice(cols.length - 1, 1);
	openMenu.value = null;
	selectForm();
}
function emptyColumn(section) {
	// Clear every field from the (single) column but keep the column.
	const col = section.columns[0];
	if (col) col.fields.splice(0);
	openMenu.value = null;
	selectForm();
}
function moveSectionsToTab(section) {
	// Move this section and every one after it into a fresh tab.
	const secs = activeTab.value.sections;
	const i = secs.indexOf(section);
	if (i < 0) return;
	const moved = secs.splice(i);
	const t = wrapTab(makeBreak("Tab Break"));
	t.sections = moved;
	tabs.value.push(t);
	openMenu.value = null;
	ensureStructure();
	activeTabIndex.value = tabs.value.length - 1;
	selectForm();
}
function sectionMenu(section) {
	const groups = [
		{ group: "Section", items: [
			{ label: "Add section below", onClick: () => addSectionBelow(section) },
			{ label: "Remove section",    onClick: () => removeSection(section) },
		] },
		{ group: "Column", items: [
			{ label: "Add column", onClick: () => addColumnTo(section) },
		] },
	];
	if (section.columns.length > 1) {
		groups[1].items.push({ label: "Remove column", onClick: () => removeColumn(section) });
	} else if (section.columns[0] && section.columns[0].fields.length) {
		groups[1].items.push({ label: "Empty column", onClick: () => emptyColumn(section) });
	}
	if (sectionIndex(section) > 0) {
		groups[0].items.push({ label: "Move to new tab", onClick: () => moveSectionsToTab(section) });
	}
	return groups;
}

function removeField(column, w) {
	const i = column.fields.indexOf(w);
	if (i >= 0) column.fields.splice(i, 1);
	if (sel.node === w) selectForm();
}
function duplicateField(column, w) {
	const src = w.df || {};
	const copy = normalizeDf({ ...src, fieldname: "", label: (src.label || "") ? src.label + " Copy" : "" });
	const nw = wrapField(copy);
	const i = column.fields.indexOf(w);
	column.fields.splice(i + 1, 0, nw);
	selectField(nw);
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
// Module is a real Frappe Module the user controls via the dropdown — never trust
// the agent to set it (it can confuse the business-process name for a module). Only
// accept an IR module that is an actual Module Def; otherwise keep "ONE BPMN".
function sanitizeModule(m) {
	if (!m) return dtModule.value || "ONE BPMN";
	if (modules.value.length && !modules.value.includes(m)) return "ONE BPMN";
	return m;
}
function loadIr(ir) {
	if (!ir) return;
	if (ir.doctype_name) dtName.value = ir.doctype_name;
	dtModule.value = sanitizeModule(ir.module);
	dtAutoname.value = ir.autoname || "";
	isChild.value = !!ir.is_child_table;
	// Only overwrite a setting the IR actually carries — an agent turn returns
	// fields without settings, so session-set settings must survive it.
	for (const k of SETTING_FLAG_KEYS) if (k in ir) dtSettings[k] = !!ir[k];
	for (const k of SETTING_INT_KEYS) if (k in ir) dtSettings[k] = Number(ir[k]) || 0;
	for (const k of SETTING_STR_KEYS) if (k in ir) dtSettings[k] = ir[k] || "";
	buildTree(ir.fields || []);
	selectForm();
	appliedName.value = "";
	applyError.value = "";
}

function settingsPayload() {
	const out = {};
	for (const k of SETTING_FLAG_KEYS) out[k] = dtSettings[k] ? 1 : 0;
	for (const k of SETTING_INT_KEYS) out[k] = Number(dtSettings[k]) || 0;
	for (const k of SETTING_STR_KEYS) out[k] = (dtSettings[k] || "").toString().trim();
	return out;
}

function currentIr() {
	return {
		doctype_name: dtName.value.trim(),
		module: dtModule.value || "ONE BPMN",
		is_child_table: isChild.value,
		autoname: dtAutoname.value || "",
		...settingsPayload(),
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
		if (Array.isArray(res)) {
			modules.value = res;
			// A module set before the list loaded (e.g. by the agent) may be bogus — fix it.
			if (dtModule.value && !res.includes(dtModule.value)) dtModule.value = "ONE BPMN";
		}
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

// Auto-save: persist the current design to the system, debounced, on every change.
function scheduleAutosave() {
	if (isRestoring) return;
	if (autosaveTimer) clearTimeout(autosaveTimer);
	autosaveTimer = setTimeout(runAutosave, 1500);
}
async function runAutosave() {
	// Only save a valid design (a name + at least one real field).
	if (!dtName.value.trim() || !contentCount.value) return;
	if (autosaveInFlight) { autosaveQueued = true; return; }
	autosaveInFlight = true;
	saveState.value = "saving";
	saveError.value = "";
	try {
		const res = await frappeRequest({
			url: `${API}apply_doctype`,
			method: "POST",
			// confirm=1: the builder edits are the user's intent — no extra prompt.
			params: { ir: JSON.stringify(currentIr()), confirm: 1 },
		});
		if (res?.name) {
			appliedName.value = res.name;
			emit("applied", res.name);   // write the DocType name back onto the shape
		}
		saveState.value = "saved";
	} catch (e) {
		saveError.value = errText(e) || "Could not save.";
		saveState.value = "error";
	} finally {
		autosaveInFlight = false;
		if (autosaveQueued) { autosaveQueued = false; scheduleAutosave(); }
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

function stopPolling() {
	pollCancelled = true;
	if (pollTimer) { clearTimeout(pollTimer); pollTimer = null; }
	if (snapTimer) { clearTimeout(snapTimer); snapTimer = null; }
	if (autosaveTimer) { clearTimeout(autosaveTimer); autosaveTimer = null; }
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
		watch([tabs, dtName, dtModule, dtAutoname, isChild, dtSettings], () => {
			scheduleSnapshot();
			scheduleAutosave();
		}, { deep: true });
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
	width: min(1640px, 98vw); height: min(960px, 96dvh);
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
.dc-chat-panel { width: clamp(320px, 30%, 460px); flex: none; display: flex; flex-direction: column; background: var(--md-surface-container-low); border-right: 1px solid var(--md-outline-variant); min-width: 0; }
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
/* Top-level view tabs (Form / Settings) */
.dc-view-tabs { display: flex; gap: 2px; padding: 6px 12px 0; background: var(--md-surface-container-low); border-bottom: 1px solid var(--md-outline-variant); }
.dc-view-tab { position: relative; border: none; background: transparent; color: var(--md-on-surface-variant); padding: 10px 16px 12px; font-size: 13px; font-weight: 500; cursor: pointer; transition: color var(--md-dur) var(--md-ease); }
.dc-view-tab:hover { color: var(--md-on-surface); }
.dc-view-tab.active { color: var(--md-primary); }
.dc-view-tab.active::after { content: ""; position: absolute; left: 12px; right: 12px; bottom: 0; height: 2px; background: var(--md-primary); border-radius: 2px 2px 0 0; }

.dc-builder-topbar { display: flex; align-items: center; gap: 10px; padding: 12px 16px; background: var(--md-surface-container-low); border-bottom: 1px solid var(--md-outline-variant); }
.dc-form-name { flex: 1; min-width: 0; }
.dc-name-input { width: 100%; border: 1px solid var(--md-outline); border-radius: var(--md-corner-sm); padding: 9px 12px; font-size: 15px; font-weight: 500; background: var(--md-surface-container-lowest); color: var(--md-on-surface); transition: border-color var(--md-dur) var(--md-ease), box-shadow var(--md-dur) var(--md-ease); }
.dc-name-input:focus { outline: none; border-color: var(--md-primary); box-shadow: inset 0 0 0 1px var(--md-primary); }

/* Settings view (whole-DocType settings, moved off the properties sidebar) */
.dc-settings-page { flex: 1; min-height: 0; overflow-y: auto; padding: 24px; display: flex; justify-content: center; }
.dc-settings-card { width: 100%; max-width: 720px; }
.dc-settings-card .dc-props-head { margin-bottom: 4px; }
/* Frappe-style settings sections: a bold section title over a 2-column grid */
.dc-settings-section { padding: 8px 0 18px; border-bottom: 1px solid var(--md-outline-variant); margin-bottom: 18px; }
.dc-settings-section:last-of-type { border-bottom: none; }
.dc-settings-title { font-size: 15px; font-weight: 600; color: var(--md-on-surface); margin-bottom: 14px; }
.dc-settings-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px 28px; align-items: start; }
.dc-settings-grid .dc-prop { margin-bottom: 0; gap: 6px; }
.dc-settings-grid .dc-prop label { font-size: 13px; font-weight: 600; color: #44546a; }
.dc-settings-grid .dc-prop-input { border: 1px solid var(--md-outline); border-radius: 8px; background: var(--md-surface-container-lowest); padding: 9px 12px; font-size: 14px; }
.dc-settings-grid .dc-prop-input:focus { outline: none; border-color: var(--md-primary); box-shadow: inset 0 0 0 1px var(--md-primary); }
.dc-settings-grid .fb-prop-check { align-self: center; }

/* ══════════════════════════════════════════════════════════════════════
   Frappe form-builder canvas — matched to the desk Form Builder look/feel.
   Frappe's CSS variables aren't present on /processa, so they're defined
   here and the markup/classes mirror Frappe's Section/Column/Field.
   ══════════════════════════════════════════════════════════════════════ */
.fb-form {
	--fg: #ffffff;
	--bg-light-gray: #f3f3f3;
	--control-bg: #ffffff;
	--fb-border: #e2e2e2;
	--fb-border-primary: #a6acb3;
	--fb-gray-400: #c7c7c7;
	--fb-heading: #171717;
	--fb-text: #383838;
	--fb-muted: #7c7c7c;
	--fb-radius: 8px;
	--fb-tsm: 13px;
	--fb-txs: 12px;

	flex: 1; min-height: 0; display: flex; flex-direction: column;
	margin: 16px; background: var(--fg);
	border: 1px solid var(--fb-border); border-radius: var(--fb-radius);
	overflow: hidden; color: var(--fb-text); font-size: var(--fb-tsm);
}

/* Tabs */
.fb-tab-header { display: flex; min-height: 42px; align-items: center; background: var(--fg); border-bottom: 1px solid var(--fb-border); padding-left: 5px; flex: none; }
.fb-tabs { display: flex; flex: 1; overflow-x: auto; }
.fb-tab { display: flex; align-items: center; gap: 6px; position: relative; padding: 10px 15px 11px; color: var(--fb-muted); min-width: max-content; cursor: pointer; }
.fb-tab::before { content: ""; position: absolute; left: 12px; right: 12px; bottom: 0; border-bottom: 2px solid transparent; }
.fb-tab:hover::before { border-color: var(--fb-gray-400); }
.fb-tab.active { font-weight: 600; color: var(--fb-heading); }
.fb-tab.active::before { border-color: var(--fb-border-primary); }
.fb-tab-edit { border: none; background: transparent; cursor: pointer; color: inherit; font-size: 11px; opacity: .55; }
.fb-tab-edit:hover { opacity: 1; }
.fb-tab-x { border: none; background: transparent; cursor: pointer; color: var(--fb-muted); font-size: 11px; margin-left: 2px; opacity: 0; transition: opacity .15s; }
.fb-tab:hover .fb-tab-x { opacity: .7; }
.fb-tab-x:hover { opacity: 1; color: #eb5757; }
.fb-tab-actions { margin-left: auto; padding: 0 12px; }
.fb-addtab { border: none; background: var(--control-bg); color: var(--fb-text); border-radius: 6px; padding: 6px 12px; font-size: var(--fb-txs); cursor: pointer; box-shadow: inset 0 0 0 1px var(--fb-border); white-space: nowrap; transition: background-color .15s; }
.fb-addtab:hover { background: var(--bg-light-gray); }

/* Canvas + sections */
.fb-canvas { flex: 1; min-height: 0; overflow-y: auto; }
.fb-section-container { background: var(--fg); border-bottom: 1px solid var(--fb-border); }
.fb-section-container:last-child { border-bottom: none; }
.fb-section { border: 1px solid transparent; border-radius: var(--fb-radius); padding: 1rem; cursor: pointer; }
.fb-section.selected { border-color: var(--fb-border-primary); }
.fb-section-header { display: flex; justify-content: space-between; align-items: center; padding-bottom: 0.75rem; }
.fb-section-label { display: flex; align-items: center; gap: 6px; }
.fb-section-grip { cursor: grab; color: var(--fb-gray-400); font-size: 14px; line-height: 1; }
.fb-section-title { font-weight: 600; color: var(--fb-heading); }
.fb-section-title.empty { font-weight: 400; font-style: italic; color: var(--fb-muted); }
.fb-section-columns { display: flex; min-height: 2rem; align-items: flex-start; }

/* Section "…" options menu (mirrors Frappe's Dropdown) */
.fb-menu-backdrop { position: fixed; inset: 0; z-index: 40; }
.fb-menu-wrap { position: relative; }
.fb-menu-btn { border: none; background: transparent; color: var(--fb-muted); font-size: 16px; line-height: 1; cursor: pointer; padding: 2px 8px; border-radius: 6px; }
.fb-menu-btn:hover { background: var(--bg-light-gray); color: var(--fb-heading); }
.fb-menu { position: absolute; top: 100%; right: 0; z-index: 50; margin-top: 4px; min-width: 180px; background: var(--fg); border: 1px solid var(--fb-border); border-radius: 10px; box-shadow: 0 8px 28px rgba(0,0,0,.16); padding: 4px; }
.fb-menu-group { padding: 4px; }
.fb-menu-group + .fb-menu-group { border-top: 1px solid var(--fb-border); }
.fb-menu-title { padding: 4px 8px; font-size: 10px; font-weight: 600; text-transform: uppercase; letter-spacing: .04em; color: var(--fb-muted); }
.fb-menu-item { display: block; width: 100%; text-align: left; border: none; background: transparent; color: var(--fb-text); font-size: var(--fb-tsm); padding: 7px 8px; border-radius: 6px; cursor: pointer; }
.fb-menu-item:hover { background: var(--bg-light-gray); }

/* Columns */
.fb-column { position: relative; display: flex; flex-direction: column; width: 100%; background: var(--bg-light-gray); border-radius: var(--fb-radius); border: 1px dashed var(--fb-gray-400); padding: 0.5rem; margin: 0 4px; }
.fb-column:first-child { margin-left: 0; }
.fb-column:last-child { margin-right: 0; }
.fb-column.selected { border-color: var(--fb-border-primary); border-style: solid; }
.fb-column-container { min-height: 2rem; display: flex; flex-direction: column; }

/* Field cards: label row + a live control preview */
.fb-field { text-align: left; width: 100%; background: var(--bg-light-gray); border-radius: var(--fb-radius); border: 1px solid transparent; padding: 0.4rem; cursor: pointer; }
.fb-field:not(:first-child) { margin-top: 0.4rem; }
.fb-field.selected, .fb-field:hover { border-color: var(--fb-border-primary); }
.fb-field.selected .fb-icon, .fb-field:hover .fb-icon { opacity: 1; }
.fb-field .field-controls { display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.3rem; }
.fb-field .field-label { display: flex; align-items: center; min-width: 0; }
.fb-field .fb-flabel { font-size: var(--fb-tsm); color: var(--fb-text); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.fb-field .fb-flabel.empty { color: var(--fb-muted); font-style: italic; }
.fb-field .reqd-asterisk { margin-left: 3px; color: #eb9091; }
.fb-field .field-actions { display: flex; gap: 2px; flex: none; }
.fb-icon { opacity: 0; border: none; background: transparent; cursor: pointer; color: var(--fb-muted); font-size: 12px; padding: 2px 4px; border-radius: 4px; transition: opacity .15s, background-color .15s, color .15s; }
.fb-icon:hover { background: var(--fg); color: var(--fb-heading); }

/* Control previews (mirror Frappe's control widgets) */
.fb-field .form-control { width: 100%; height: 28px; border: none; border-radius: var(--fb-radius); background: var(--control-bg); padding: 6px 8px; font-size: var(--fb-tsm); color: var(--fb-text); box-shadow: inset 0 0 0 1px var(--fb-border); }
.fb-field textarea.form-control { height: auto; resize: none; }
.fb-field select.form-control { appearance: none; }
.fb-check { display: inline-flex; align-items: center; }
.fb-check input { width: 14px; height: 14px; }
.fb-table-preview { border: 1px dashed var(--fb-gray-400); border-radius: var(--fb-radius); padding: 8px 10px; font-size: var(--fb-txs); color: var(--fb-muted); background: var(--control-bg); }
.fb-heading-preview { font-weight: 700; color: var(--fb-heading); font-size: 15px; }
.fb-html-preview { border: 1px dashed var(--fb-gray-400); border-radius: var(--fb-radius); padding: 12px; text-align: center; font-size: var(--fb-txs); color: var(--fb-muted); }

/* Add buttons */
.fb-add-field { padding: 8px 2px 2px; }
.fb-add-btn { border: none; background: var(--fg); color: var(--fb-muted); border-radius: 6px; padding: 6px 12px; font-size: var(--fb-txs); cursor: pointer; box-shadow: inset 0 0 0 1px var(--fb-border); transition: background-color .15s, color .15s; }
.fb-add-btn:hover { background: var(--bg-light-gray); color: var(--fb-heading); }

/* Auto-save status */
.dc-save-status { font-size: 13px; color: var(--md-on-surface-variant); }
.dc-save-status.st-saving { color: var(--md-primary); }
.dc-save-status.st-saved { color: var(--md-success); }
.dc-save-status.st-error { color: var(--md-error); }

/* ── Properties (right) ── */
.dc-props-panel { width: clamp(250px, 22%, 312px); flex: none; border-left: 1px solid var(--md-outline-variant); background: var(--md-surface-container-low); overflow-y: auto; padding: 18px 16px; }
.dc-props-head { font-size: 14px; font-weight: 600; letter-spacing: .01em; color: var(--md-on-surface); margin-bottom: 16px; }
.dc-prop { display: flex; flex-direction: column; gap: 5px; margin-bottom: 14px; }
.dc-prop label { font-size: 12px; color: var(--md-on-surface-variant); font-weight: 500; }
/* MD3 outlined text field */
.dc-prop-input { border: 1px solid var(--md-outline); border-radius: var(--md-corner-xs); padding: 10px 12px; font-size: 14px; font-family: inherit; background: var(--md-surface-container-lowest); color: var(--md-on-surface); transition: border-color var(--md-dur) var(--md-ease), box-shadow var(--md-dur) var(--md-ease); }
.dc-prop-input:hover { border-color: var(--md-on-surface); }
.dc-prop-input:focus { outline: none; border-color: var(--md-primary); box-shadow: inset 0 0 0 1px var(--md-primary); }
.dc-mono { font-family: ui-monospace, monospace; }

/* ── Field properties (Frappe-style: sticky search + scroll + filled) ── */
.fb-props-header { position: sticky; top: -18px; z-index: 3; display: flex; align-items: center; gap: 6px; margin: -18px -16px 12px; padding: 10px 12px; background: var(--md-surface-container-low); border-bottom: 1px solid var(--md-outline-variant); }
.fb-props-search { flex: 1; display: flex; align-items: center; gap: 6px; background: var(--md-surface-container-high); border-radius: var(--md-corner-full); padding: 6px 12px; }
.fb-props-search-ico { color: var(--md-on-surface-variant); font-size: 15px; }
.fb-props-search input { flex: 1; min-width: 0; border: none; background: transparent; outline: none; font-size: 13px; color: var(--md-on-surface); }
.fb-props-search-x { border: none; background: transparent; color: var(--md-on-surface-variant); cursor: pointer; font-size: 11px; padding: 0 2px; }
.fb-props-close { flex: none; border: none; background: transparent; color: var(--md-on-surface-variant); cursor: pointer; font-size: 13px; width: 28px; height: 28px; border-radius: var(--md-corner-full); }
.fb-props-close:hover { background: rgba(71,70,79,var(--md-state-hover)); color: var(--md-on-surface); }
.fb-props-body { display: flex; flex-direction: column; padding-bottom: 4px; }
/* Frappe controls: bold-ish label above a soft filled field */
.fb-props-body .dc-prop { gap: 6px; margin-bottom: 16px; }
.fb-props-body .dc-prop label { font-size: 13px; font-weight: 600; color: #44546a; }
.fb-props-body .dc-prop-input { border: 1px solid transparent; background: var(--md-surface-container-high); border-radius: 8px; padding: 8px 10px; font-size: 13px; }
.fb-props-body .dc-prop-input:hover { background: color-mix(in srgb, var(--md-on-surface) 3%, var(--md-surface-container-high)); }
.fb-props-body .dc-prop-input:focus { background: var(--md-surface-container-lowest); border-color: var(--md-primary); box-shadow: inset 0 0 0 1px var(--md-primary); }
.fb-props-body textarea.dc-prop-input { resize: vertical; min-height: 40px; }
/* Code / *_depends_on fields read as a small code box */
.fb-props-body textarea.dc-prop-input.dc-mono { min-height: 54px; background: var(--md-surface-container-high); line-height: 1.5; }
.fb-prop-check { display: flex; align-items: center; gap: 10px; padding: 7px 4px; font-size: 13px; font-weight: 600; color: #44546a; cursor: pointer; border-radius: 6px; }
.fb-prop-check:hover { background: rgba(71,70,79,var(--md-state-hover)); }
.fb-prop-check input[type="checkbox"] { width: 16px; height: 16px; accent-color: var(--md-primary); cursor: pointer; flex: none; }
.fb-prop-hint { font-size: 12px; color: #6b7684; line-height: 1.45; margin: 5px 0 0; }
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
.dc-count { color: var(--md-on-surface-variant); font-size: 13px; margin-right: auto; }

/* ── History group (undo/redo/templates) ── */
.dc-hist-group { display: flex; gap: 6px; align-items: center; }
.dc-icon-sm { border: none; background: transparent; color: var(--md-on-surface-variant); border-radius: var(--md-corner-full); width: 34px; height: 34px; font-size: 16px; cursor: pointer; transition: background-color var(--md-dur) var(--md-ease); }
.dc-icon-sm:hover:not(:disabled) { background: rgba(71,70,79,var(--md-state-hover)); }
.dc-icon-sm:disabled { opacity: .35; cursor: not-allowed; }

/* ══════════════════════════════════════════════════════════════════════
   Responsive (MD3 adaptive dialog): panels flex on medium widths, and the
   three-pane layout stacks into a full-screen, single-column flow on small
   screens so nothing overflows on laptops/tablets/phones.
   ══════════════════════════════════════════════════════════════════════ */
@media (max-width: 1100px) {
	.dc-chat-panel { width: clamp(260px, 30%, 380px); }
	.dc-props-panel { width: clamp(220px, 25%, 290px); }
	.dc-form-name { flex-basis: 100%; }   /* name input takes its own row */
}
@media (max-width: 760px) {
	.dc-window { width: 100vw; height: 100dvh; max-height: 100dvh; border-radius: 0; }
	.dc-root { flex-direction: column; }
	.dc-chat-panel {
		width: 100%; height: 42%; min-height: 160px; flex: none;
		border-right: none; border-bottom: 1px solid var(--md-outline-variant);
	}
	.dc-builder-panel { width: 100%; flex: 1 1 auto; min-height: 0; }
	.dc-props-panel {
		width: 100%; height: auto; max-height: 46%; flex: none;
		border-left: none; border-top: 1px solid var(--md-outline-variant);
	}
	.dc-window-header { padding: 10px 12px 10px 14px; }
	.dc-subtitle { display: none; }        /* keep the header compact */
	.dc-settings-page { padding: 16px; }
	.dc-settings-grid { grid-template-columns: 1fr; gap: 10px; }
}
@media (max-width: 420px) {
	.dc-dt-chip { max-width: 120px; }
}
</style>
