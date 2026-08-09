<template>
	<div class="lc-root">

		<!-- ── LEFT: Chat (WI-001677: the shared AgentChatPanel) ──────────
		     Both Logix surfaces (this split view and the LogixChat modal) now
		     embed one implementation. Script changes arrive as
		     onefm.script_diff cards — CREATE and MODIFY both round-trip; the
		     apply-target wiring into the editor below is preserved in
		     onLogixCardAction. DISAMBIGUATE rides the shared onefm.choice. -->
		<div class="lc-chat-panel">
			<AgentChatPanel
				agent-id="logix_agent"
				variant="docked"
				:context="logixTurnContext"
				:cards="cardRegistry"
				@card-action="onLogixCardAction"
			/>
		</div>

		<!-- ── CENTER: Code Editor Panel ────────────────────────────── -->
		<div class="lc-editor-panel">

			<!-- File bar -->
			<div class="lc-file-bar">
				<div class="lc-file-name-area">
					<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" width="14" height="14">
						<path stroke-linecap="round" stroke-linejoin="round" d="M19.5 14.25v-2.625a3.375 3.375 0 00-3.375-3.375h-1.5A1.125 1.125 0 0113.5 7.125v-1.5a3.375 3.375 0 00-3.375-3.375H8.25m0 12.75h7.5m-7.5 3H12M10.5 2.25H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 00-9-9z"/>
					</svg>
					<span v-if="!isEditingName" class="lc-filename" @dblclick="startEditName" title="Double-click to rename">
						{{ canvasScriptName || 'Untitled' }}
					</span>
					<input
						v-else
						ref="nameInputEl"
						v-model="canvasScriptName"
						class="lc-name-input"
						placeholder="Script name..."
						@blur="stopEditName"
						@keydown.enter="stopEditName"
						@keydown.escape="stopEditName"
					/>
				</div>
				<div class="lc-file-actions">
					<!-- Save status -->
					<span v-if="isSaving" class="lc-save-status lc-autosaving">
						<span class="lc-spinner-sm"></span> Saving…
					</span>
					<span v-else-if="isDirty && !isSaved" class="lc-save-status lc-unsaved">● Unsaved</span>
					<span v-else-if="isSaved" class="lc-save-status lc-saved">✓ Saved</span>

					<!-- Live security-lint status -->
					<span
						v-if="lintViolations.length"
						class="lc-save-status lc-lint-status"
						:title="lintViolations.join('\n')"
					>⚠ {{ lintViolations.length }} security issue{{ lintViolations.length > 1 ? 's' : '' }}</span>

					<div v-if="isLoadingScript" class="lc-loading-indicator">
						<div class="lc-spinner-sm"></div>
						Loading...
					</div>

					<!-- Folder / Script Browser button -->
					<div class="lc-script-browser-wrap">
						<button
							class="lc-file-btn"
							:class="{ 'lc-file-btn--active': showScriptBrowser }"
							@click="toggleScriptBrowser"
							title="Browse server scripts"
						>
							<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" width="14" height="14">
								<path stroke-linecap="round" stroke-linejoin="round" d="M3 7a2 2 0 012-2h3.5L10 7h9a2 2 0 012 2v8a2 2 0 01-2 2H5a2 2 0 01-2-2V7z"/>
							</svg>
						</button>
						<!-- Script browser dropdown -->
						<div v-if="showScriptBrowser" class="lc-script-dropdown">
							<div class="lc-script-dropdown-header">
								<span>Server Scripts</span>
								<div v-if="loadingScriptBrowser" class="lc-spinner-sm"></div>
							</div>
							<div class="lc-script-dropdown-search">
								<input
									v-model="scriptBrowserSearch"
									type="text"
									placeholder="Search scripts..."
									class="lc-script-search-input"
									@click.stop
								/>
							</div>
							<div class="lc-script-dropdown-list">
								<div v-if="loadingScriptBrowser && !filteredScriptBrowserList.length" class="lc-script-dropdown-empty">Loading…</div>
								<div v-else-if="filteredScriptBrowserList.length === 0" class="lc-script-dropdown-empty">No scripts found</div>
								<div
									v-for="s in filteredScriptBrowserList"
									:key="s.name"
									class="lc-script-dropdown-item"
									:class="{ 'lc-script-dropdown-item--active': s.name === canvasScriptName }"
									@click="linkExistingScript(s.name)"
								>
									<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" width="12" height="12" class="lc-script-item-icon">
										<path stroke-linecap="round" stroke-linejoin="round" d="M19.5 14.25v-2.625a3.375 3.375 0 00-3.375-3.375h-1.5A1.125 1.125 0 0113.5 7.125v-1.5a3.375 3.375 0 00-3.375-3.375H8.25m0 12.75h7.5m-7.5 3H12M10.5 2.25H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 00-9-9z"/>
									</svg>
									<div class="lc-script-item-info">
										<div class="lc-script-item-name">{{ s.name }}</div>
										<div class="lc-script-item-type">{{ s.script_type }}</div>
									</div>
									<svg v-if="s.name === canvasScriptName" viewBox="0 0 24 24" fill="currentColor" width="12" height="12" class="lc-script-item-check">
										<path d="M9 16.17L4.83 12l-1.42 1.41L9 19 21 7l-1.41-1.41z"/>
									</svg>
								</div>
							</div>
						</div>
					</div>

					<button class="lc-file-btn" @click="copyCanvas" title="Copy script">
						<svg viewBox="0 0 24 24" fill="currentColor" width="14" height="14">
							<path d="M16 1H4c-1.1 0-2 .9-2 2v14h2V3h12V1zm3 4H8c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h11c1.1 0 2-.9 2-2V7c0-1.1-.9-2-2-2zm0 16H8V7h11v14z"/>
						</svg>
						Copy
					</button>
					<button
						class="lc-file-btn"
						:class="{ 'lc-file-btn--active': showVersionHistory }"
						@click="showVersionHistory = !showVersionHistory"
						title="Version History"
					>
						<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" width="14" height="14">
							<circle cx="12" cy="12" r="10"/>
							<polyline points="12 6 12 12 16 14"/>
						</svg>
					</button>
				</div>
			</div>

			<!-- Backdrop to close dropdowns when clicking outside -->
			<div v-if="showDoctypeDropdown || showModuleDropdown || showScriptBrowser" class="lc-dropdown-backdrop" @click="showDoctypeDropdown = false; showModuleDropdown = false; showScriptBrowser = false"></div>

			<!-- Script Settings Panel -->
			<div class="lc-settings-panel">
					<div class="lc-settings-grid">
						<!-- Script Type -->
						<div class="lc-settings-field">
							<label class="lc-settings-label">Script Type</label>
							<select v-model="scriptMeta.script_type" class="lc-settings-select">
								<option value="API">API</option>
								<option value="DocType Event">DocType Event</option>
								<option value="Scheduler Event">Scheduler Event</option>
								<option value="Permission Query">Permission Query</option>
							</select>
						</div>

						<!-- Module -->
						<div class="lc-settings-field">
							<label class="lc-settings-label">Module</label>
							<div class="lc-settings-dropdown-wrap">
								<input
									v-model="moduleSearch"
									type="text"
									:placeholder="scriptMeta.module || 'Search Module...'"
									class="lc-settings-input"
									@focus="showModuleDropdown = true; showDoctypeDropdown = false; moduleSearch = ''"
								/>
								<div v-if="showModuleDropdown && filteredModuleOptions.length > 0" class="lc-settings-dropdown">
									<div v-for="m in filteredModuleOptions" :key="m" @mousedown.prevent="scriptMeta.module = m; moduleSearch = m; showModuleDropdown = false" class="lc-settings-dropdown-item">{{ m }}</div>
								</div>
							</div>
						</div>

						<!-- DocType (for DocType Event / Permission Query) -->
						<template v-if="['DocType Event', 'Permission Query'].includes(scriptMeta.script_type)">
							<div class="lc-settings-field">
								<label class="lc-settings-label">Reference DocType</label>
								<div class="lc-settings-dropdown-wrap">
									<input
										v-model="doctypeSearch"
										type="text"
										:placeholder="scriptMeta.reference_doctype || 'Search DocType...'"
										class="lc-settings-input"
										@focus="showDoctypeDropdown = true; showModuleDropdown = false; doctypeSearch = ''"
									/>
									<div v-if="showDoctypeDropdown && filteredDoctypeOptions.length > 0" class="lc-settings-dropdown">
										<div v-for="dt in filteredDoctypeOptions" :key="dt" @mousedown.prevent="scriptMeta.reference_doctype = dt; doctypeSearch = dt; showDoctypeDropdown = false" class="lc-settings-dropdown-item">{{ dt }}</div>
									</div>
								</div>
							</div>
							<div v-if="scriptMeta.script_type === 'DocType Event'" class="lc-settings-field">
								<label class="lc-settings-label">DocType Event</label>
								<select v-model="scriptMeta.doctype_event" class="lc-settings-select">
									<option value="">Select event...</option>
									<option v-for="e in DOCTYPE_EVENTS" :key="e" :value="e">{{ e }}</option>
								</select>
							</div>
						</template>

						<!-- API fields -->
						<template v-if="scriptMeta.script_type === 'API'">
							<div class="lc-settings-field">
								<label class="lc-settings-label">API Method</label>
								<input v-model="scriptMeta.api_method" type="text" placeholder="e.g. my_api" class="lc-settings-input" />
							</div>
							<div class="lc-settings-field lc-settings-field--inline">
								<label class="lc-settings-label">Allow Guest</label>
								<input type="checkbox" v-model="scriptMeta.allow_guest" class="lc-settings-checkbox" />
							</div>
						</template>

						<!-- Scheduler Event fields -->
						<template v-if="scriptMeta.script_type === 'Scheduler Event'">
							<div class="lc-settings-field">
								<label class="lc-settings-label">Event Frequency</label>
								<select v-model="scriptMeta.event_frequency" class="lc-settings-select">
									<option value="">Select frequency...</option>
									<option v-for="f in EVENT_FREQUENCIES" :key="f" :value="f">{{ f }}</option>
								</select>
							</div>
							<div v-if="scriptMeta.event_frequency === 'Cron'" class="lc-settings-field">
								<label class="lc-settings-label">Cron Format</label>
								<input v-model="scriptMeta.cron_format" type="text" placeholder="*/5 * * * *" class="lc-settings-input" />
							</div>
						</template>
					</div>
			</div>

			<!-- Security-lint banner: what's wrong with the script, live -->
			<div v-if="lintViolations.length" class="lc-lint-banner">
				<div class="lc-lint-banner-head">
					<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="14" height="14">
						<path stroke-linecap="round" stroke-linejoin="round" d="M12 9v4m0 4h.01M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z"/>
					</svg>
					{{ lintViolations.length }} security issue{{ lintViolations.length > 1 ? 's' : '' }} — must be fixed before this script can be saved or deployed
				</div>
				<ul class="lc-lint-list">
					<li v-for="(v, i) in lintViolations" :key="i">{{ v }}</li>
				</ul>
			</div>

			<!-- Code area with syntax highlighting -->
			<div class="lc-code-area">
				<CodeMirrorEditor
					v-model="canvasCode"
					language="python"
					placeholder="# Script will appear here after chatting with Logix or loading an existing script..."
					@change="onCodeInput"
				/>
			</div>

		</div>

		<!-- ── RIGHT: Version History Panel ──────────────────── -->
		<Transition name="lc-slide-in">
			<div v-if="showVersionHistory" class="lc-version-panel">
				<div class="lc-version-panel-header">
					<span>Version History</span>
					<button class="lc-ver-refresh-btn" @click="fetchVersionHistory" :disabled="loadingVersions" title="Refresh">
						<svg viewBox="0 0 24 24" fill="currentColor" width="13" height="13" :class="{ 'lc-spin': loadingVersions }">
							<path d="M17.65 6.35A7.958 7.958 0 0 0 12 4c-4.42 0-7.99 3.58-7.99 8s3.57 8 7.99 8c3.73 0 6.84-2.55 7.73-6h-2.08A5.99 5.99 0 0 1 12 18c-3.31 0-6-2.69-6-6s2.69-6 6-6c1.66 0 3.14.69 4.22 1.78L13 11h7V4l-2.35 2.35z"/>
						</svg>
					</button>
				</div>

				<div v-if="loadingVersions" class="lc-version-empty">
					<div class="lc-ver-spinner"></div>
					<p>Loading history…</p>
				</div>
				<div v-else-if="!canvasScriptName" class="lc-version-empty">
					<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" width="28" height="28">
						<circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/>
					</svg>
					<p>No script linked.</p>
					<p class="lc-version-empty-sub">Save the script first.</p>
				</div>
				<div v-else-if="versions.length === 0" class="lc-version-empty">
					<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" width="28" height="28">
						<circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/>
					</svg>
					<p>No history yet.</p>
					<p class="lc-version-empty-sub">Save changes to start tracking versions.</p>
				</div>

				<div v-for="(v, idx) in versions" :key="v.version_name" class="lc-version-item" :class="{ 'lc-version-active': v.is_current }">
					<div class="lc-version-top">
						<div class="lc-version-top-left">
							<span class="lc-version-num">V{{ versions.length - idx }}</span>
							<span v-if="v.is_current" class="lc-active-badge">Current</span>
						</div>
						<span class="lc-version-time">{{ formatCreation(v.creation) }}</span>
					</div>
					<div class="lc-version-author">{{ v.author }}</div>
					<div class="lc-version-desc">{{ v.description }}</div>
					<div class="lc-version-links">
						<button v-if="!v.is_current" class="lc-ver-link" @click="toggleDiff(v)">[View Diff]</button>
						<button v-if="!v.is_current" class="lc-ver-link" @click="restoreVersion(v)">[Restore]</button>
					</div>
					<!-- Inline diff -->
					<div v-if="diffVersion?.version_name === v.version_name && versionDiffRows.length" class="lc-inline-diff">
						<div class="lc-inline-diff-header">
							<span>V{{ versions.length - idx }}</span>
							<span>Current</span>
						</div>
						<div class="lc-inline-diff-body">
							<div v-for="(row, ri) in versionDiffRows" :key="ri" class="lc-diff-row">
								<pre :class="['lc-diff-cell', diffCellClass(row, 'left')]">{{ row.left ?? '' }}</pre>
								<pre :class="['lc-diff-cell', diffCellClass(row, 'right')]">{{ row.right ?? '' }}</pre>
							</div>
						</div>
					</div>
				</div>
			</div>
		</Transition>
	</div>
</template>

<script setup>
import { ref, computed, nextTick, onMounted, watch } from "vue";
import CodeMirrorEditor from "./CodeMirrorEditor.vue";
import { frappeRequest } from "frappe-ui";
// WI-001677: the chat half is the shared AgentChatPanel; script changes
// arrive as onefm.script_diff cards and apply into the editor below,
// test cases as onefm.test_cases cards that run against the linked script.
import { AgentChatPanel } from "@/components/chat";
import { cardRegistry } from "@/components/chat/cards/registry";

const props = defineProps({
	element:        { type: Object,  default: null },
	scriptType:     { type: String,  default: "bpmn:script" },
	currentScript:  { type: String,  default: "" },
	eventBus:       { type: Object,  default: null },
	processContext: { type: Object,  default: null },
});

const emit = defineEmits(["close", "script-saved", "back"]);

// ── Canvas state ──────────────────────────────────────────────────────
const canvasScriptName = ref(props.currentScript || "");
const savedScriptName  = ref(props.currentScript || ""); // tracks the name currently in the DB
const canvasCode       = ref("");
const isEditingName    = ref(false);
const nameInputEl      = ref(null);
const isDirty          = ref(false);
const isSaving         = ref(false);
const isSaved          = ref(false);
const isLoadingScript  = ref(false);

// ── Live security lint ────────────────────────────────────────────────
// Mirrors the pre-deployment gate so the author sees blocking issues as they
// type — same checks that will reject a save/deploy.
const lintViolations = ref([]);
let lintTimer = null;

async function runSecurityLint() {
	const code = canvasCode.value || "";
	if (!code.trim()) {
		lintViolations.value = [];
		return;
	}
	try {
		const res = await frappeRequest({
			url: "/api/method/one_bpmn.api.script_security.lint_server_script",
			method: "POST",
			params: { code },
		});
		lintViolations.value = res && res.violations ? res.violations : [];
	} catch (e) {
		// Never let a lint failure disrupt editing.
		lintViolations.value = [];
	}
}

watch(canvasCode, () => {
	if (lintTimer) clearTimeout(lintTimer);
	lintTimer = setTimeout(runSecurityLint, 400);
});

// ── Auto-save ─────────────────────────────────────────────────────────
let autoSaveTimer = null;
let isInitializing = false;

// ── Script metadata ───────────────────────────────────────────────────
const scriptMeta = ref({
	script_type: "API",
	reference_doctype: "",
	doctype_event: "",
	api_method: "",
	allow_guest: false,
	event_frequency: "",
	cron_format: "",
	module: "",
});
const doctypeOptions = ref([]);
const moduleOptions  = ref([]);
const showDoctypeDropdown = ref(false);
const showModuleDropdown  = ref(false);
const doctypeSearch  = ref("");
const moduleSearch   = ref("");
const filteredDoctypeOptions = computed(() => {
	const q = doctypeSearch.value.toLowerCase();
	return q ? doctypeOptions.value.filter((d) => d.toLowerCase().includes(q)) : doctypeOptions.value;
});
const filteredModuleOptions = computed(() => {
	const q = moduleSearch.value.toLowerCase();
	return q ? moduleOptions.value.filter((m) => m.toLowerCase().includes(q)) : moduleOptions.value;
});

const DOCTYPE_EVENTS = [
	"Before Insert", "Before Validate", "Before Save", "After Insert",
	"After Save", "Before Rename", "After Rename", "Before Submit",
	"After Submit", "Before Cancel", "After Cancel", "Before Delete",
	"After Delete", "Before Save (Submitted Document)",
	"After Save (Submitted Document)", "Before Print", "On Payment Authorization",
];
const EVENT_FREQUENCIES = [
	"All", "Hourly", "Daily", "Weekly", "Monthly", "Yearly",
	"Hourly Long", "Daily Long", "Weekly Long", "Monthly Long", "Cron",
];

async function loadDoctypeOptions() {
	if (doctypeOptions.value.length) return;
	try {
		const rows = await frappeRequest({
			url: "/api/method/frappe.client.get_list",
			params: { doctype: "DocType", fields: JSON.stringify(["name"]), limit_page_length: 0, order_by: "name asc" },
		});
		doctypeOptions.value = (rows || []).map((x) => x.name);
	} catch (e) { console.error("Failed to load DocTypes", e); }
}
async function loadModuleOptions() {
	if (moduleOptions.value.length) return;
	try {
		const rows = await frappeRequest({
			url: "/api/method/frappe.client.get_list",
			params: { doctype: "Module Def", fields: JSON.stringify(["name"]), limit_page_length: 0, order_by: "name asc" },
		});
		moduleOptions.value = (rows || []).map((x) => x.name);
	} catch (e) { console.error("Failed to load Modules", e); }
}

// ── Version history ───────────────────────────────────────────────────
const showVersionHistory = ref(false);
const versions           = ref([]);
const loadingVersions    = ref(false);
const diffVersion        = ref(null);
const versionDiffRows    = ref([]);

// ── Script browser ────────────────────────────────────────────────────
const showScriptBrowser    = ref(false);
const scriptBrowserList    = ref([]);
const loadingScriptBrowser = ref(false);
const scriptBrowserSearch  = ref("");

const filteredScriptBrowserList = computed(() => {
	const q = scriptBrowserSearch.value.toLowerCase();
	return q ? scriptBrowserList.value.filter(s => s.name.toLowerCase().includes(q) || (s.script_type || "").toLowerCase().includes(q)) : scriptBrowserList.value;
});

async function toggleScriptBrowser() {
	showScriptBrowser.value = !showScriptBrowser.value;
	if (showScriptBrowser.value && !scriptBrowserList.value.length) {
		await fetchScriptBrowserList();
	}
}

async function fetchScriptBrowserList() {
	loadingScriptBrowser.value = true;
	try {
		const rows = await frappeRequest({
			url: "/api/method/frappe.client.get_list",
			params: {
				doctype: "Server Script",
				fields: JSON.stringify(["name", "script_type"]),
				limit_page_length: 0,
				order_by: "modified desc",
			},
		});
		scriptBrowserList.value = rows || [];
	} catch (e) {
		console.error("Failed to load script list:", e);
	} finally {
		loadingScriptBrowser.value = false;
	}
}

async function linkExistingScript(name) {
	showScriptBrowser.value = false;
	isInitializing = true;
	try {
		canvasScriptName.value = name;
		savedScriptName.value  = name;
		isLoadingScript.value  = true;
		const msg = await frappeRequest({
			url: "/api/method/frappe.client.get",
			params: { doctype: "Server Script", name },
		});
		canvasCode.value = msg?.script || "";
		scriptMeta.value = {
			script_type:       msg?.script_type || "API",
			reference_doctype: msg?.reference_doctype || "",
			doctype_event:     msg?.doctype_event || "",
			api_method:        msg?.api_method || "",
			allow_guest:       !!msg?.allow_guest,
			event_frequency:   msg?.event_frequency || "",
			cron_format:       msg?.cron_format || "",
			module:            msg?.module || "",
		};
		if (props.eventBus && props.element) {
			props.eventBus.fire("spiff.script.update", {
				element:    props.element,
				scriptType: props.scriptType,
				script:     name,
			});
		}
		isDirty.value = false;
		isSaved.value = false;
		await fetchVersionHistory();
	} catch (e) {
		console.error("Failed to link script:", e);
	} finally {
		isLoadingScript.value = false;
		isInitializing = false;
	}
}

// ── Chat wiring (WI-001677) ───────────────────────────────────────────
// The shared AgentChatPanel owns transcript/composer/lifecycle; this host
// owns what card actions mean.

const logixTurnContext = computed(() => ({
	element_name: elementLabel.value || canvasScriptName.value || "",
	// The launch paths differ: the properties-panel launcher loads the script
	// into canvas state without setting the prop — the canvas's own state is
	// the truth (fixed after a live turn where the map couldn't see the
	// script and asked the user to paste it).
	current_script: savedScriptName.value || canvasScriptName.value || props.currentScript || "",
	process_context: props.processContext || null,
}));

async function onLogixCardAction({ name, action, value, payload }) {
	if (name === "onefm.test_cases" && action === "run-test") {
		await runTestCase(payload);
		return;
	}
	if (name !== "onefm.script_diff" || action !== "apply-script") return;
	const code = value.modified_script || "";
	if (!code) return;
	// Same editor handoff as the legacy approve_modify / approve_create
	// handlers: set the canvas, mark dirty, save through the one path that
	// owns naming, linking and version history.
	if (value.mode === "CREATE" && value.suggested_name && !canvasScriptName.value) {
		canvasScriptName.value = value.suggested_name;
	}
	canvasCode.value = code;
	isDirty.value = true;
	isSaved.value = false;
	await saveScript();
}

// The TestCaseCard renders and requests; the host runs — it owns the
// linked-script name, so the endpoint call lives here, not in the card.
async function runTestCase(payload) {
	const report = payload && typeof payload.onResult === "function" ? payload.onResult : () => {};
	if (!savedScriptName.value) {
		report({ passed: false, summary: "Save the script first — there is nothing to run yet." });
		return;
	}
	try {
		const result = await frappeRequest({
			url: "/api/method/one_bpmn.api.server_script_api.run_logix_test_case",
			method: "POST",
			params: {
				script_name: savedScriptName.value,
				inputs: JSON.stringify(payload.inputs || {}),
			},
		});
		report({
			passed: result?.passed ?? false,
			summary: result?.summary || (result?.passed ? "Test passed." : "Test failed."),
		});
	} catch (err) {
		report({ passed: false, summary: "Could not run the test — network error." });
	}
}

// ── Element label ─────────────────────────────────────────────────────
const elementLabel = computed(() => {
	if (!props.element) return "";
	const bo = props.element.businessObject;
	return bo?.name || props.element.id || "";
});

// ── Lifecycle ─────────────────────────────────────────────────────────
onMounted(async () => {
	loadDoctypeOptions();
	loadModuleOptions();
	await initCanvas();
});

async function initCanvas() {
	isInitializing = true;
	try {
		if (props.currentScript) {
			canvasScriptName.value = props.currentScript;
			savedScriptName.value  = props.currentScript;
			isLoadingScript.value  = true;
			try {
				const msg = await frappeRequest({
					url: "/api/method/frappe.client.get",
					params: { doctype: "Server Script", name: props.currentScript },
				});
				canvasCode.value = msg?.script || "";
				scriptMeta.value = {
					script_type:       msg?.script_type || "API",
					reference_doctype: msg?.reference_doctype || "",
					doctype_event:     msg?.doctype_event || "",
					api_method:        msg?.api_method || "",
					allow_guest:       !!msg?.allow_guest,
					event_frequency:   msg?.event_frequency || "",
					cron_format:       msg?.cron_format || "",
					module:            msg?.module || "",
				};
			} catch (e) {
				console.error("Failed to load script:", e);
			} finally {
				isLoadingScript.value = false;
			}
			await fetchVersionHistory();
		} else {
			// Auto-set display name from the BPMN element label; savedScriptName stays ""
			// until the first successful auto-save confirms it exists in the DB.
			canvasScriptName.value = elementLabel.value || "";
			savedScriptName.value  = "";
			canvasCode.value = "";
			if (props.element?.type === "bpmn:ScriptTask") {
				scriptMeta.value.script_type = "API";
			}
		}
	} finally {
		isInitializing = false;
	}
}

// ── Code editor helpers ───────────────────────────────────────────────
function onCodeInput() {
	isDirty.value = true;
	isSaved.value = false;
	scheduleAutoSave();
}

// syncScroll removed — CodeMirror handles scroll sync natively

function startEditName() {
	isEditingName.value = true;
	nextTick(() => {
		nameInputEl.value?.select();
	});
}

async function stopEditName() {
	isEditingName.value = false;
	const newName = canvasScriptName.value.trim();
	if (newName && newName !== savedScriptName.value) {
		// New name — ensure it doesn't collide with an unrelated existing script
		await ensureUniqueName();
	}
	scheduleAutoSave();
}

async function copyCanvas() {
	try { await navigator.clipboard.writeText(canvasCode.value); } catch { /* fallback */ }
}

// ── Version history (real API) ───────────────────────────────────────
async function fetchVersionHistory() {
	if (!canvasScriptName.value) { versions.value = []; return; }
	loadingVersions.value = true;
	try {
		const data = await frappeRequest({
			url: "/api/method/one_bpmn.api.script_version_history.get_script_version_history",
			params: { script_name: canvasScriptName.value },
		});
		versions.value = data || [];
	} catch (e) {
		console.error("Failed to fetch version history:", e);
		versions.value = [];
	} finally {
		loadingVersions.value = false;
	}
}

function formatCreation(creation) {
	if (!creation) return "";
	try {
		return new Date(creation).toLocaleString(undefined, {
			month: "short", day: "numeric",
			hour: "2-digit", minute: "2-digit"
		});
	} catch { return creation; }
}

function toggleDiff(version) {
	if (diffVersion.value?.version_name === version.version_name) {
		diffVersion.value = null;
		versionDiffRows.value = [];
		return;
	}
	diffVersion.value = version;
	const oldLines = (version.script || "").split("\n");
	const newLines = (canvasCode.value || "").split("\n");
	const rows = [];
	const maxLen = Math.max(oldLines.length, newLines.length);
	for (let i = 0; i < maxLen; i++) {
		const l = oldLines[i] ?? null;
		const r = newLines[i] ?? null;
		if (l === r) rows.push({ type: "unchanged", left: l, right: r });
		else if (l === null) rows.push({ type: "added", left: null, right: r });
		else if (r === null) rows.push({ type: "deleted", left: l, right: null });
		else rows.push({ type: "changed", left: l, right: r });
	}
	versionDiffRows.value = rows;
}

function diffCellClass(row, side) {
	if (row.type === "hunk")      return "lc-sdiff-hunk";
	if (row.type === "unchanged") return "";
	if (row.type === "deleted")   return side === "left"  ? "lc-sdiff-del"  : "lc-sdiff-empty";
	if (row.type === "added")     return side === "right" ? "lc-sdiff-add"  : "lc-sdiff-empty";
	if (row.type === "changed")   return side === "left"  ? "lc-sdiff-del"  : "lc-sdiff-add";
	return "";
}

async function restoreVersion(version) {
	canvasCode.value  = version.script || "";
	isDirty.value     = true;
	isSaved.value     = false;
	diffVersion.value = null;
	scheduleAutoSave();
}

// ── Auto-save scheduler ───────────────────────────────────────────────
function scheduleAutoSave() {
	if (isInitializing) return;
	if (autoSaveTimer) clearTimeout(autoSaveTimer);
	autoSaveTimer = setTimeout(() => { saveScript(); }, 1500);
}

// Watch metadata changes and auto-save
watch(scriptMeta, () => { scheduleAutoSave(); }, { deep: true });

// ── Unique name helper ────────────────────────────────────────────────
async function ensureUniqueName() {
	const base = canvasScriptName.value.trim();
	if (!base) return;
	let name = base;
	let counter = 1;
	while (true) {
		try {
			// A name that matches the currently saved script is always fine (it's ours)
			if (name === savedScriptName.value) break;
			const d = await frappeRequest({
				url: "/api/method/one_bpmn.api.server_script_api.check_server_script_exists",
				params: { script_name: name },
			});
			if (!d?.exists) break;
			name = `${base} ${counter++}`;
		} catch { break; }
	}
	canvasScriptName.value = name;
}

// ── Save script ───────────────────────────────────────────────────────
async function saveScript() {
	const name = canvasScriptName.value.trim();
	if (!name) return; // silently wait — user hasn't named the script yet

	isSaving.value = true;
	try {
		// If the script was previously saved under a different name, rename it first
		if (savedScriptName.value && savedScriptName.value !== name) {
			await frappeRequest({
				url: "/api/method/frappe.client.rename_doc",
				method: "POST",
				params: { doctype: "Server Script", name: savedScriptName.value, new_name: name },
			});
			savedScriptName.value = name;
		}

		// Upsert with the (possibly renamed) name
		const meta = scriptMeta.value;
		const data = await frappeRequest({
			url: "/api/method/one_bpmn.api.server_script_api.create_server_script",
			method: "POST",
			params: {
				script_name:       name,
				script_type:       meta.script_type || "API",
				script:            canvasCode.value,
				reference_doctype: meta.reference_doctype || undefined,
				doctype_event:     meta.doctype_event || undefined,
				api_method:        meta.api_method || undefined,
				allow_guest:       meta.allow_guest ? 1 : 0,
				event_frequency:   meta.event_frequency || undefined,
				cron_format:       meta.cron_format || undefined,
				module:            meta.module || undefined,
			},
		});
		const scriptName = data?.name || name;
		canvasScriptName.value = scriptName;
		savedScriptName.value  = scriptName;

		// Fire BPMN event to link the script to the element
		if (props.eventBus && props.element) {
			props.eventBus.fire("spiff.script.update", {
				element:    props.element,
				scriptType: props.scriptType,
				script:     scriptName,
			});
		}

		isDirty.value = false;
		isSaved.value = true;
		setTimeout(() => { isSaved.value = false; }, 3000);

		emit("script-saved", scriptName);
		await fetchVersionHistory();
	} catch (err) {
		console.error("Auto-save failed:", err);
	} finally {
		isSaving.value = false;
	}
}

// Conversation lifecycle (create / resume / end-on-unmount) is owned by the
// shared AgentChatPanel — no chat teardown left to do here.
</script>

<style scoped>
/* ── Root: 3-pane flex layout ───────────────────────────────────────── */
.lc-root {
	display: flex;
	flex-direction: row;
	height: 84vh;
	min-height: 560px;
	overflow: hidden;
	font-family: "Google Sans", Roboto, "Segoe UI", system-ui, sans-serif;
	background: #fff;
}

/* ═══════════════════════════════════════════════════════════════════
   CHAT PANEL (left)
══════════════════════════════════════════════════════════════════ */
.lc-chat-panel {
	width: 580px;
	flex-shrink: 0;
	display: flex;
	flex-direction: column;
	border-right: 1px solid #eee;
	background: #fff;
	min-width: 0;
}

/* ── Diff cell colors (version-panel inline diff) ────────────────── */
.lc-sdiff-del   { background: rgba(240,80,80,.2);    color: #ff8a8a; }
.lc-sdiff-add   { background: rgba(100,220,100,.18); color: #6ee68e; }
.lc-sdiff-hunk  { background: rgba(144,202,249,.08); color: #90caf9; font-style: italic; }
.lc-sdiff-empty { background: rgba(255,255,255,.03); }

/* ═══════════════════════════════════════════════════════════════════
   CODE EDITOR PANEL (center)
══════════════════════════════════════════════════════════════════ */
.lc-editor-panel {
	flex: 1;
	display: flex;
	flex-direction: column;
	min-width: 0;
	border-right: 1px solid #eee;
	background: #fafafa;
}

/* ── File bar ───────────────────────────────────────────────────── */
.lc-file-bar {
	display: flex;
	align-items: center;
	justify-content: space-between;
	padding: 8px 14px;
	background: #fff;
	border-bottom: 1px solid #eee;
	flex-shrink: 0;
	gap: 10px;
}

.lc-file-name-area {
	display: flex;
	align-items: center;
	gap: 7px;
	min-width: 0;
	flex: 1;
	color: #555;
}

.lc-filename {
	font-size: 13px;
	font-weight: 500;
	color: #171717;
	white-space: nowrap;
	overflow: hidden;
	text-overflow: ellipsis;
	cursor: text;
}

.lc-filename:hover { text-decoration: underline; }

.lc-name-input {
	flex: 1;
	border: 1px solid #171717;
	border-radius: 4px;
	padding: 2px 8px;
	font-size: 13px;
	font-weight: 500;
	color: #171717;
	outline: none;
	background: #fff;
}

.lc-loading-indicator {
	display: flex;
	align-items: center;
	gap: 6px;
	font-size: 12px;
	color: #888;
}

.lc-file-actions {
	display: flex;
	align-items: center;
	gap: 6px;
	flex-shrink: 0;
}

.lc-file-btn {
	display: flex;
	align-items: center;
	gap: 5px;
	border: 1px solid #e0e0e0;
	border-radius: 5px;
	background: #fff;
	color: #555;
	font-size: 12px;
	padding: 4px 10px;
	cursor: pointer;
	transition: background 0.15s, border-color 0.15s;
	font-family: inherit;
}

.lc-file-btn:hover { background: #f5f5f5; border-color: #ccc; }
.lc-file-btn--active { background: #f3f3f3; border-color: #171717; color: #171717; }

/* ── Save status in file bar ────────────────────────────────────────── */
.lc-save-status {
	font-size: 11px;
	display: flex;
	align-items: center;
	gap: 4px;
	white-space: nowrap;
}
.lc-unsaved   { color: #e65100; }
.lc-saved     { color: #2e7d32; }
.lc-autosaving { color: #888; }
.lc-lint-status { color: #c62828; font-weight: 600; cursor: default; }

/* ── Security-lint banner ───────────────────────────────────────────── */
.lc-lint-banner {
	flex: 0 0 auto;
	margin: 6px 8px 0;
	border: 1px solid #f3c2c2;
	background: #fdecec;
	border-radius: 6px;
	padding: 8px 10px;
	font-size: 11.5px;
	color: #8a1c1c;
	max-height: 120px;
	overflow-y: auto;
}
.lc-lint-banner-head {
	display: flex;
	align-items: center;
	gap: 6px;
	font-weight: 600;
	margin-bottom: 4px;
}
.lc-lint-list {
	margin: 0;
	padding-left: 22px;
	list-style: disc;
}
.lc-lint-list li { margin: 2px 0; line-height: 1.35; word-break: break-word; }

/* ── Script browser ─────────────────────────────────────────────────── */
.lc-script-browser-wrap {
	position: relative;
}

.lc-script-dropdown {
	position: absolute;
	right: 0;
	top: calc(100% + 6px);
	z-index: 250;
	width: 260px;
	background: #fff;
	border: 1px solid #ddd;
	border-radius: 8px;
	box-shadow: 0 6px 20px rgba(0,0,0,.12);
	display: flex;
	flex-direction: column;
	overflow: hidden;
}

.lc-script-dropdown-header {
	display: flex;
	align-items: center;
	justify-content: space-between;
	padding: 8px 12px;
	font-size: 11px;
	font-weight: 700;
	color: #555;
	text-transform: uppercase;
	letter-spacing: 0.04em;
	border-bottom: 1px solid #eee;
	background: #fafafa;
}

.lc-script-dropdown-search {
	padding: 6px 8px;
	border-bottom: 1px solid #eee;
}

.lc-script-search-input {
	width: 100%;
	border: 1px solid #ddd;
	border-radius: 5px;
	padding: 4px 8px;
	font-size: 12px;
	outline: none;
	color: #171717;
	background: #fff;
	box-sizing: border-box;
}

.lc-script-search-input:focus { border-color: #171717; box-shadow: 0 0 0 2px rgba(108,63,224,.1); }

.lc-script-dropdown-list {
	max-height: 220px;
	overflow-y: auto;
}

.lc-script-dropdown-empty {
	padding: 16px 12px;
	text-align: center;
	font-size: 12px;
	color: #aaa;
}

.lc-script-dropdown-item {
	display: flex;
	align-items: center;
	gap: 8px;
	padding: 7px 12px;
	cursor: pointer;
	transition: background 0.12s;
	border-bottom: 1px solid #f5f5f5;
}

.lc-script-dropdown-item:last-child { border-bottom: none; }
.lc-script-dropdown-item:hover { background: #f8f8f8; }
.lc-script-dropdown-item--active { background: #f3f3f3; }

.lc-script-item-icon { flex-shrink: 0; color: #888; }
.lc-script-item-check { flex-shrink: 0; color: #171717; margin-left: auto; }

.lc-script-item-info {
	flex: 1;
	min-width: 0;
}

.lc-script-item-name {
	font-size: 12px;
	font-weight: 500;
	color: #171717;
	white-space: nowrap;
	overflow: hidden;
	text-overflow: ellipsis;
}

.lc-script-item-type {
	font-size: 10px;
	color: #888;
	margin-top: 1px;
}

/* ── Script Settings Panel ──────────────────────────────────────── */
.lc-settings-panel {
	background: #fafafa;
	border-bottom: 1px solid #e8e8e8;
	padding: 10px 14px;
	flex-shrink: 0;
}
.lc-settings-grid {
	display: flex;
	flex-wrap: wrap;
	gap: 10px 16px;
	align-items: flex-end;
}
.lc-settings-field {
	display: flex;
	flex-direction: column;
	gap: 3px;
	min-width: 140px;
	flex: 1 1 140px;
	max-width: 220px;
}
.lc-settings-field--inline {
	flex-direction: row;
	align-items: center;
	gap: 8px;
	min-width: auto;
	flex: 0 0 auto;
}
.lc-settings-label {
	font-size: 10px;
	font-weight: 600;
	color: #666;
	text-transform: uppercase;
	letter-spacing: 0.04em;
}
.lc-settings-input,
.lc-settings-select {
	height: 28px;
	padding: 0 8px;
	font-size: 12px;
	border: 1px solid #ddd;
	border-radius: 6px;
	background: #fff;
	color: #171717;
	outline: none;
	width: 100%;
}
.lc-settings-input:focus,
.lc-settings-select:focus { border-color: #171717; box-shadow: 0 0 0 2px rgba(108,63,224,.1); }
.lc-dropdown-backdrop {
	position: fixed;
	inset: 0;
	z-index: 199;
}
.lc-settings-dropdown-wrap { position: relative; }
.lc-settings-dropdown {
	position: absolute;
	z-index: 200;
	top: 100%;
	left: 0;
	right: 0;
	max-height: 160px;
	overflow-y: auto;
	background: #fff;
	border: 1px solid #ddd;
	border-radius: 6px;
	box-shadow: 0 4px 12px rgba(0,0,0,.1);
	margin-top: 2px;
}
.lc-settings-dropdown-item {
	padding: 5px 10px;
	font-size: 12px;
	cursor: pointer;
	color: #171717;
}
.lc-settings-dropdown-item:hover { background: #f3f3f3; color: #171717; }
.lc-settings-checkbox { width: 14px; height: 14px; accent-color: #171717; cursor: pointer; }

.lc-settings-slide-enter-active,
.lc-settings-slide-leave-active { transition: max-height 0.2s ease, opacity 0.2s ease; max-height: 200px; overflow: hidden; }
.lc-settings-slide-enter-from,
.lc-settings-slide-leave-to { max-height: 0; opacity: 0; }

/* ── Code area ──────────────────────────────────────────────────── */
.lc-code-area {
	flex: 1;
	display: flex;
	overflow: hidden;
	background: #fafafa;
}


/* ── Spinners ───────────────────────────────────────────────────── */
.lc-spinner-sm {
	width: 12px;
	height: 12px;
	border: 2px solid #ddd;
	border-top-color: #666;
	border-radius: 50%;
	animation: lc-spin 0.7s linear infinite;
	display: inline-block;
}

@keyframes lc-spin { to { transform: rotate(360deg); } }

/* ═══════════════════════════════════════════════════════════════════
   VERSION HISTORY PANEL (right, slides in)
══════════════════════════════════════════════════════════════════ */
.lc-version-panel {
	width: 240px;
	flex-shrink: 0;
	background: #fff;
	border-left: 1px solid #eee;
	display: flex;
	flex-direction: column;
	overflow: hidden;
}

.lc-version-panel-header {
	padding: 10px 14px;
	font-size: 13px;
	font-weight: 600;
	color: #171717;
	border-bottom: 1px solid #eee;
	flex-shrink: 0;
	display: flex;
	align-items: center;
	justify-content: space-between;
}

.lc-ver-refresh-btn {
	width: 26px;
	height: 26px;
	border-radius: 50%;
	border: none;
	background: transparent;
	color: #171717;
	cursor: pointer;
	display: flex;
	align-items: center;
	justify-content: center;
	transition: background 0.15s;
}
.lc-ver-refresh-btn:hover { background: rgba(108, 63, 224, 0.1); }
.lc-ver-refresh-btn:disabled { opacity: 0.4; cursor: default; }

.lc-ver-spinner {
	width: 22px;
	height: 22px;
	border: 2.5px solid #e0d6f7;
	border-top-color: #171717;
	border-radius: 50%;
	animation: lc-spin 0.7s linear infinite;
}

.lc-spin {
	animation: lc-spin 0.7s linear infinite;
}

.lc-version-panel > .lc-version-empty,
.lc-version-panel > .lc-version-item {
	overflow-y: auto;
}

/* Make the items scrollable */
.lc-version-panel {
	overflow-y: auto;
}

/* ── Empty state ────────────────────────────────────────────────── */
.lc-version-empty {
	display: flex;
	flex-direction: column;
	align-items: center;
	justify-content: center;
	padding: 30px 20px;
	text-align: center;
	color: #aaa;
	gap: 8px;
	font-size: 12px;
}

.lc-version-empty p { margin: 0; }
.lc-version-empty-sub { font-size: 11px; color: #bbb; }

/* ── Version item ───────────────────────────────────────────────── */
.lc-version-item {
	padding: 10px 14px;
	border-bottom: 1px solid #f0f0f0;
	cursor: default;
	transition: background 0.12s;
}

.lc-version-item:hover { background: #fafafa; }

.lc-version-active {
	border-left: 3px solid #171717;
	background: #f8f8f8;
}

.lc-version-top {
	display: flex;
	align-items: center;
	justify-content: space-between;
	margin-bottom: 3px;
}

.lc-version-top-left {
	display: flex;
	align-items: center;
	gap: 5px;
}

.lc-version-num {
	font-size: 12px;
	font-weight: 600;
	color: #171717;
}

.lc-active-badge {
	background: linear-gradient(135deg, #171717 0%, #525252 100%);
	color: #fff;
	font-size: 10px;
	font-weight: 600;
	border-radius: 100px;
	padding: 1px 7px;
}

.lc-version-time {
	font-size: 11px;
	color: #888;
}

.lc-version-author {
	font-size: 12px;
	font-weight: 500;
	color: #333;
	margin-bottom: 2px;
}

.lc-version-desc {
	font-size: 11px;
	color: #666;
	margin-bottom: 4px;
}

.lc-version-links {
	display: flex;
	gap: 6px;
}

.lc-ver-link {
	background: none;
	border: none;
	padding: 0;
	font-size: 11px;
	color: #171717;
	cursor: pointer;
	font-family: inherit;
	text-decoration: underline;
}

.lc-ver-link:hover { color: #5430b0; }

/* ── Inline diff (inside version panel) ────────────────────────── */
.lc-inline-diff {
	margin-top: 8px;
	border: 1px solid #e0e0e0;
	border-radius: 5px;
	overflow: hidden;
}

.lc-inline-diff-header {
	display: flex;
	background: #f5f5f5;
	border-bottom: 1px solid #e0e0e0;
}

.lc-inline-diff-header span {
	flex: 1;
	padding: 3px 8px;
	font-size: 10px;
	font-weight: 600;
	color: #666;
}

.lc-inline-diff-header span:first-child { border-right: 1px solid #e0e0e0; }

.lc-inline-diff-body {
	background: #171717;
	max-height: 180px;
	overflow-y: auto;
}

.lc-diff-row {
	display: flex;
	border-bottom: 1px solid rgba(255,255,255,.04);
	min-height: 16px;
}

.lc-diff-cell {
	flex: 1;
	margin: 0;
	padding: 1px 6px;
	font-family: monospace;
	font-size: 10px;
	line-height: 1.5;
	color: #e6e1e5;
	white-space: pre-wrap;
	overflow: hidden;
	min-width: 0;
	border-right: 1px solid rgba(255,255,255,.08);
}

.lc-diff-cell:last-child { border-right: none; }

/* ── Slide transition ───────────────────────────────────────────── */
.lc-slide-in-enter-active,
.lc-slide-in-leave-active {
	transition: width 0.22s ease, opacity 0.18s ease;
	overflow: hidden;
}

.lc-slide-in-enter-from,
.lc-slide-in-leave-to {
	width: 0;
	opacity: 0;
}
</style>
