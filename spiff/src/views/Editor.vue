<template>
	<div class="h-full flex flex-col">
		<!-- Unified Toolbar -->
		<header class="bg-white border-b px-2 py-2 flex items-center justify-between shadow-sm w-full min-h-[48px]">
			
			<div class="flex items-center gap-2 flex-1 min-w-0">
				<!-- Left: Back & Title -->
				<div class="flex items-center gap-2 pr-3 border-r border-gray-200 shrink-0">
					<button
						@click="goBack"
						class="p-1.5 hover:bg-gray-100 rounded-md transition-colors text-gray-600"
						title="Back to list"
					>
						<Icon icon="lucide:chevron-left" class="w-5 h-5" />
					</button>
					<div class="flex items-center gap-2">
						<h1 class="text-sm font-semibold text-gray-800 truncate max-w-[200px]" :title="processName">{{ processName }}</h1>
						<Badge v-if="processStatus" :theme="getStatusTheme(processStatus)" :label="processStatus" size="sm" />
					</div>
				</div>

				<!-- CENTER: BPMN Tools Container (Mounted natively from BpmnEditor.vue) -->
				<div id="bpmn-editor-toolbar" class="flex-1 flex items-center h-8 min-w-0"></div>
			</div>
			
			<div class="flex items-center gap-2 shrink-0 border-l border-gray-200 pl-3 ml-2">
				
				<!-- Hidden file input for BPMN import -->
				<input
					ref="importFileInput"
					type="file"
					accept=".bpmn"
					class="hidden"
					@change="handleImportFile"
				/>
				<!-- File menu dropdown -->
				<div class="relative">
					<button
						@click="showFileMenu = !showFileMenu"
						class="w-8 h-8 flex items-center justify-center hover:bg-gray-100 rounded transition-colors text-gray-600"
						title="Import / Export"
					>
						<Icon icon="lucide:menu" class="w-4 h-4" />
					</button>
					<div
						v-if="showFileMenu"
						v-click-outside="() => showFileMenu = false"
						class="absolute right-0 mt-1 w-36 bg-white border border-gray-200 rounded-lg shadow-lg z-50 py-1"
					>
						<button
							@click="triggerImport(); showFileMenu = false"
							class="w-full flex items-center gap-2 px-3 py-2 text-sm text-gray-700 hover:bg-gray-50 transition-colors"
						>
							<Icon icon="lucide:download" class="w-4 h-4" />
							Import
						</button>
						<button
							@click="exportCurrentDiagram(); showFileMenu = false"
							class="w-full flex items-center gap-2 px-3 py-2 text-sm text-gray-700 hover:bg-gray-50 transition-colors"
							:disabled="!activeDiagramName"
							:class="{ 'opacity-40 cursor-not-allowed': !activeDiagramName }"
						>
							<Icon icon="lucide:upload" class="w-4 h-4" />
							Export
						</button>
					</div>
				</div>

				<!-- Shape Library Toggle - DISABLED (see DEVELOPMENT_CONTEXT.md)
				<button
					@click="showShapeLibrary = !showShapeLibrary"
					:class="[
						'p-2 rounded-md transition-colors',
						showShapeLibrary ? 'bg-gray-300 text-gray-800' : 'hover:bg-gray-300 text-gray-600'
					]"
					title="Toggle Shape Library"
				>
					<Icon icon="lucide:shapes" class="w-5 h-5" />
				</button>
				-->
			</div>
		</header>

		<!-- Notification Alert -->
		<div v-if="notification.show" class="px-4 py-2">
			<Alert
				:title="notification.title"
				:theme="notification.theme"
				:description="notification.message"
				closable
				v-model="notification.show"
			/>
		</div>

		<!-- Main Content -->
		<div class="flex-1 flex flex-col overflow-hidden">
			<!-- Canvas Area with Shape Library -->
			<div class="flex-1 flex overflow-hidden">
				<!-- Shape Library Panel - DISABLED (see DEVELOPMENT_CONTEXT.md)
				<ShapeLibraryPanel
					v-if="showShapeLibrary"
					@shape-drag-start="onShapeDragStart"
				/>
				-->

				<!-- Canvas -->

				<div class="flex-1 relative">
					<!-- Loading state -->
					<div v-if="loading" class="flex items-center justify-center h-full bg-gray-100">
						<div class="text-center">
							<div
								class="animate-spin rounded-full h-12 w-12 border-b-2 border-gray-700 mx-auto mb-4"
							></div>
							<p class="text-gray-500">Loading...</p>
						</div>
					</div>

					<!-- Single long-lived modeler instance; mounts on first diagram selection.
					     Clipboard state (globalClipboardData) lives at module scope so it
					     survives unmount — v-if is safe here and defers the heavy init. -->
					<BpmnEditor
						v-if="activeDiagramName"
						ref="editorRef"
						class="absolute inset-0"
						:save-status-text="saveStatusText"
						:save-status-color="saveStatusColor"
						@ready="onEditorReady"
						@changed="onDiagramChanged"
						@zoom-changed="onZoomChanged"
						@launch-script-editor="onLaunchScriptEditor"
						@launch-markdown-editor="onLaunchMarkdownEditor"
						@launch-callactivity-editor="onLaunchCallActivityEditor"
						@launch-callactivity-search="onLaunchCallActivitySearch"
					/>

					<!-- No-diagram placeholder: only shown when not loading and no diagram is selected -->
					<div
						v-if="!loading && !activeDiagramName"
						class="flex items-center justify-center h-full bg-gray-100"
					>
						<div class="text-center">
							<div class="text-gray-400 mb-6">
								<Icon icon="lucide:layout-grid" class="w-20 h-20 mx-auto" />
							</div>
							<p class="text-gray-500 text-lg mb-6">No diagram selected</p>
							<button
								@click="showAddDiagramDialog"
								class="inline-flex items-center gap-2 px-5 py-3 bg-gray-700 hover:bg-gray-800 text-white rounded-lg transition-colors font-medium"
							>
								<Icon icon="lucide:plus" class="w-5 h-5" />
								Add Process Diagram
							</button>
						</div>
					</div>
				</div>
			</div>

			<!-- Tab Bar -->
			<div v-if="openTabs.length > 0" class="flex items-center justify-between bg-gray-50 border-t border-gray-200 min-h-[40px]">
				<EditorTabs
					:tabs="openTabs"
					:activeTab="activeDiagramName"
					@select-tab="selectDiagram"
					@add-tab="showAddDiagramDialog"
					@rename-tab="renameProcessModel"
					class="flex-1 min-w-0"
				/>
				
				<!-- Zoom Controls -->
				<div class="flex items-center gap-1 px-3 py-2 border-l border-gray-300">
					<button
						@click="handleZoomOut"
						class="p-1.5 rounded hover:bg-gray-300 text-gray-600 transition-colors"
						title="Zoom Out (Ctrl+-)"
					>
						<Icon icon="lucide:minus" class="w-4 h-4" />
					</button>
					<button
						@click="handleResetZoom"
						class="px-2 py-1 rounded hover:bg-gray-300 text-gray-700 text-sm font-medium min-w-[50px] text-center transition-colors"
						title="Reset Zoom"
					>
						{{ zoomLevel }}%
					</button>
					<button
						@click="handleZoomIn"
						class="p-1.5 rounded hover:bg-gray-300 text-gray-600 transition-colors"
						title="Zoom In (Ctrl++)"
					>
						<Icon icon="lucide:plus" class="w-4 h-4" />
					</button>
					<button
						@click="handleFitToScreen"
						class="p-1.5 rounded hover:bg-gray-300 text-gray-600 transition-colors ml-1"
						title="Fit to Screen"
					>
						<Icon icon="lucide:maximize-2" class="w-4 h-4" />
					</button>
				</div>
			</div>
		</div>

		<!-- Add Diagram Dialog -->
		<Dialog v-model="showNewDiagramDialog" :options="{ title: 'New Diagram' }">
			<template #body-content>
				<div class="space-y-4">
					<FormControl
						label="Diagram Name"
						v-model="newDiagramName"
						:required="true"
						placeholder="Enter diagram name"
					/>
					<FormControl
						label="Description"
						type="textarea"
						v-model="newDiagramDescription"
						placeholder="Optional description"
					/>
				</div>
			</template>
			<template #actions>
				<div class="flex gap-2">
					<Button variant="subtle" @click="showNewDiagramDialog = false">Cancel</Button>
					<Button variant="solid" @click="createDiagram" :loading="creating">Create</Button>
				</div>
			</template>
		</Dialog>

		<!-- Server Script Selector/Creator Dialog -->
		<Dialog v-model="showScriptEditorDialog" :options="{ title: scriptEditorTitle, size: '5xl' }">
			<template #body-content>
				<div class="space-y-4">
					<!-- Mode Tabs -->
					<div class="flex border-b border-gray-200">
						<button
							@click="scriptDialogMode = 'select'"
							:class="[
								'px-4 py-2 text-sm font-medium border-b-2 transition-colors -mb-px',
								scriptDialogMode === 'select'
									? 'border-blue-500 text-blue-600'
									: 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'
							]"
						>
							<Icon icon="lucide:search" class="w-4 h-4 inline mr-1.5" />
							Select Existing
						</button>
						<button
							@click="scriptDialogMode = 'create'"
							:class="[
								'px-4 py-2 text-sm font-medium border-b-2 transition-colors -mb-px',
								scriptDialogMode === 'create'
									? 'border-blue-500 text-blue-600'
									: 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'
							]"
						>
							<Icon icon="lucide:plus" class="w-4 h-4 inline mr-1.5" />
							Create New
						</button>
					</div>

					<!-- Select Existing Mode -->
					<div v-if="scriptDialogMode === 'select'" class="space-y-3">
						<div class="text-sm text-gray-500">
							Search and select an existing Server Script to link.
						</div>
						<!-- Search input -->
						<div class="relative">
							<Icon icon="lucide:search" class="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
							<input
								v-model="serverScriptSearch"
								type="text"
								placeholder="Search server scripts..."
								class="w-full pl-10 pr-3 py-2 border border-gray-300 rounded-lg text-sm bg-white text-gray-900 focus:outline-none focus:ring-2 focus:ring-blue-400 focus:border-blue-400"
							/>
						</div>
						<!-- Script list -->
						<div class="max-h-72 overflow-y-auto border border-gray-200 rounded-lg">
							<div v-if="loadingScripts" class="p-6 text-center text-gray-400">
								<div class="animate-spin rounded-full h-6 w-6 border-b-2 border-gray-400 mx-auto mb-2"></div>
								Loading scripts...
							</div>
							<div v-else-if="filteredServerScripts.length === 0" class="p-6 text-center text-gray-400">
								No server scripts found.
							</div>
							<div
								v-else
								v-for="script in filteredServerScripts"
								:key="script.name"
								@click="selectedServerScript = script.name"
								:class="[
									'flex items-center justify-between px-4 py-3 cursor-pointer border-b border-gray-100 last:border-b-0 transition-colors',
									selectedServerScript === script.name
										? 'bg-blue-50 border-l-4 border-l-blue-500'
										: 'hover:bg-gray-50'
								]"
							>
								<div>
									<div class="text-sm font-medium text-gray-900">{{ script.name }}</div>
									<div class="text-xs text-gray-500 mt-0.5">
										{{ script.script_type }}
										<span v-if="script.reference_doctype"> · {{ script.reference_doctype }}</span>
									</div>
								</div>
								<div class="flex items-center gap-2">
									<span v-if="script.disabled" class="text-xs bg-red-100 text-red-700 px-2 py-0.5 rounded-full">Disabled</span>
									<Icon v-if="selectedServerScript === script.name" icon="lucide:check-circle" class="w-5 h-5 text-blue-500" />
								</div>
							</div>
						</div>
					</div>

					<!-- Create New Mode -->
					<div v-else-if="scriptDialogMode === 'create'" class="space-y-4">
						<div class="text-sm text-gray-500">
							Create a new Server Script and link it to this element.
						</div>
						<!-- Row 1: Name + Script Type -->
						<div class="grid grid-cols-2 gap-4">
							<div>
								<label class="block text-xs font-medium text-gray-700 mb-1">Script Name <span class="text-red-500">*</span></label>
								<input
									v-model="newScript.name"
									type="text"
									placeholder="e.g. Validate Employee Shift"
									class="w-full px-3 py-1.5 border border-gray-300 rounded-md text-sm bg-white text-gray-900 focus:outline-none focus:ring-2 focus:ring-blue-400"
								/>
							</div>
							<div>
								<label class="block text-xs font-medium text-gray-700 mb-1">Script Type <span class="text-red-500">*</span></label>
								<select
									v-model="newScript.script_type"
									class="w-full px-3 py-1.5 border border-gray-300 rounded-md text-sm bg-white text-gray-900 focus:outline-none focus:ring-2 focus:ring-blue-400"
									:disabled="isScriptTaskElement"
								>
									<template v-if="isScriptTaskElement">
										<option value="API">API</option>
									</template>
									<template v-else>
										<option value="">Select type...</option>
										<option value="DocType Event">DocType Event</option>
										<option value="Scheduler Event">Scheduler Event</option>
										<option value="Permission Query">Permission Query</option>
										<option value="API">API</option>
									</template>
								</select>
							</div>
						</div>

						<!-- Conditional Row 2: DocType Event fields -->
						<div v-if="['DocType Event', 'Permission Query'].includes(newScript.script_type)" class="grid grid-cols-2 gap-4">
							<div>
								<label class="block text-xs font-medium text-gray-700 mb-1">Reference DocType</label>
								<div class="relative">
									<input
										v-model="doctypeSearch"
										type="text"
										:placeholder="newScript.reference_doctype || 'Search DocType...'"
										class="w-full px-3 py-1.5 border border-gray-300 rounded-md text-sm bg-white text-gray-900 focus:outline-none focus:ring-2 focus:ring-blue-400"
										@focus="showDoctypeDropdown = true; showModuleDropdown = false; doctypeSearch = ''"
										@blur="setTimeout(() => showDoctypeDropdown = false, 200)"
									/>
									<div v-if="showDoctypeDropdown && filteredDoctypeOptions.length > 0" class="absolute z-50 w-full mt-1 max-h-48 overflow-y-auto bg-white border border-gray-200 rounded-md shadow-lg">
										<div
											v-for="dt in filteredDoctypeOptions"
											:key="dt"
											@mousedown.prevent="newScript.reference_doctype = dt; doctypeSearch = dt; showDoctypeDropdown = false"
											class="px-3 py-1.5 text-sm cursor-pointer hover:bg-blue-50 text-gray-900"
										>{{ dt }}</div>
									</div>
								</div>
							</div>
							<div v-if="newScript.script_type === 'DocType Event'">
								<label class="block text-xs font-medium text-gray-700 mb-1">DocType Event</label>
								<select
									v-model="newScript.doctype_event"
									class="w-full px-3 py-1.5 border border-gray-300 rounded-md text-sm bg-white text-gray-900 focus:outline-none focus:ring-2 focus:ring-blue-400"
								>
									<option value="">Select event...</option>
									<option v-for="evt in doctypeEvents" :key="evt" :value="evt">{{ evt }}</option>
								</select>
							</div>
						</div>

						<!-- Conditional: API fields -->
						<div v-if="newScript.script_type === 'API'" class="grid grid-cols-2 gap-4">
							<div>
								<label class="block text-xs font-medium text-gray-700 mb-1">API Method</label>
								<input
									v-model="newScript.api_method"
									type="text"
									placeholder="e.g. my_custom_api"
									class="w-full px-3 py-1.5 border border-gray-300 rounded-md text-sm bg-white text-gray-900 focus:outline-none focus:ring-2 focus:ring-blue-400"
								/>
							</div>
							<div class="flex items-end">
								<label class="flex items-center gap-2 text-sm text-gray-700 cursor-pointer">
									<input type="checkbox" v-model="newScript.allow_guest" class="rounded border-gray-300" />
									Allow Guest
								</label>
							</div>
						</div>

						<!-- Conditional: Scheduler Event fields -->
						<div v-if="newScript.script_type === 'Scheduler Event'" class="grid grid-cols-2 gap-4">
							<div>
								<label class="block text-xs font-medium text-gray-700 mb-1">Event Frequency</label>
								<select
									v-model="newScript.event_frequency"
									class="w-full px-3 py-1.5 border border-gray-300 rounded-md text-sm bg-white text-gray-900 focus:outline-none focus:ring-2 focus:ring-blue-400"
								>
									<option value="">Select frequency...</option>
									<option v-for="freq in eventFrequencies" :key="freq" :value="freq">{{ freq }}</option>
								</select>
							</div>
							<FormControl
								v-if="newScript.event_frequency === 'Cron'"
								label="Cron Format"
								v-model="newScript.cron_format"
								placeholder="*/5 * * * *"
							/>
						</div>

						<!-- Module -->
						<div>
							<label class="block text-xs font-medium text-gray-700 mb-1">Module (for export)</label>
							<div class="relative">
								<input
									v-model="moduleSearch"
									type="text"
									:placeholder="newScript.module || 'Search Module...'"
									class="w-full px-3 py-1.5 border border-gray-300 rounded-md text-sm bg-white text-gray-900 focus:outline-none focus:ring-2 focus:ring-blue-400"
									@focus="showModuleDropdown = true; showDoctypeDropdown = false; moduleSearch = ''"
									@blur="setTimeout(() => showModuleDropdown = false, 200)"
								/>
								<div v-if="showModuleDropdown && filteredModuleOptions.length > 0" class="absolute z-50 w-full mt-1 max-h-48 overflow-y-auto bg-white border border-gray-200 rounded-md shadow-lg">
									<div
										v-for="mod in filteredModuleOptions"
										:key="mod"
										@mousedown.prevent="newScript.module = mod; moduleSearch = mod; showModuleDropdown = false"
										class="px-3 py-1.5 text-sm cursor-pointer hover:bg-blue-50 text-gray-900"
									>{{ mod }}</div>
								</div>
							</div>
						</div>

						<!-- Script content -->
						<div>
							<label class="block text-xs font-medium text-gray-700 mb-1">Script <span class="text-red-500">*</span></label>
							<textarea
								v-model="newScript.script"
								class="w-full h-48 p-3 font-mono text-sm border border-gray-300 rounded-lg bg-gray-50 text-gray-900 focus:outline-none focus:ring-2 focus:ring-blue-400 focus:border-blue-400 resize-y"
								placeholder="# Enter Python script here..."
								spellcheck="false"
							></textarea>
						</div>
					</div>
				</div>
			</template>
			<template #actions>
				<div class="flex gap-2">
					<Button variant="subtle" @click="showScriptEditorDialog = false">Cancel</Button>
					<Button
						v-if="scriptDialogMode === 'select'"
						variant="solid"
						@click="saveScript"
						:disabled="!selectedServerScript"
					>Link Script</Button>
					<Button
						v-else
						variant="solid"
						@click="createAndLinkScript"
						:loading="creatingScript"
						:disabled="!newScript.name || !newScript.script_type || !newScript.script"
					>Create & Link</Button>
				</div>
			</template>
		</Dialog>

		<!-- Call Activity Search Dialog -->
		<CallActivitySearchDialog
			v-model="showCallActivitySearchDialog"
			:search-event="callActivitySearchEvent"
			@select="onCallActivitySelected"
			@cancel="onCancelCallActivitySearch"
		/>

		<!-- Markdown Editor Dialog -->
		<Dialog v-model="showMarkdownEditorDialog" :options="{ title: 'Edit Instructions (Markdown)', size: '4xl' }">
			<template #body-content>
				<div class="space-y-3">
					<div class="text-sm text-gray-500">
						Edit the markdown content for this element's instructions.
					</div>
					<TextEditor
						editor-class="prose-sm min-h-[16rem] border rounded-b-lg border-t-0 p-3"
						:content="markdownEditorContent"
						placeholder="Type instructions here..."
						@change="(val) => (markdownEditorContent = val)"
						:bubbleMenu="true"
						:fixedMenu="true"
					/>
				</div>
			</template>
			<template #actions>
				<div class="flex gap-2">
					<Button variant="subtle" @click="showMarkdownEditorDialog = false">Cancel</Button>
					<Button variant="solid" @click="saveMarkdown">Save</Button>
				</div>
			</template>
		</Dialog>

		<!-- Unsaved Navigation Warning Dialog -->
		<Dialog v-model="showUnsavedNavigationWarning" :options="{ title: 'Unsaved Changes', size: 'sm' }">
			<template #body-content>
				<div class="text-base text-gray-700">
					You have unsaved changes. Are you sure you want to leave? Your pending edits will be lost.
				</div>
			</template>
			<template #actions>
				<div class="flex gap-2 justify-end w-full">
					<Button variant="subtle" @click="cancelNavigation">No, stay here</Button>
					<Button variant="solid" theme="red" @click="confirmNavigation">Yes, leave</Button>
				</div>
			</template>
		</Dialog>
	</div>
</template>

<script setup>
import { ref, onMounted, onUnmounted, computed, watch, nextTick } from "vue";
import { useRouter, useRoute, onBeforeRouteLeave } from "vue-router";
import { frappeRequest, TextEditor } from "frappe-ui";
import { Icon } from "@iconify/vue";
import BpmnEditor from "@/components/BpmnEditor.vue";
import EditorTabs from "@/components/EditorTabs.vue";
import ShapeLibraryPanel from "@/components/ShapeLibraryPanel.vue";
import { downloadBpmn } from "@/utils/downloadBpmn";
import CallActivitySearchDialog from "@/components/CallActivitySearchDialog.vue";

const props = defineProps({
	process: {
		type: String,
		required: true,
	},
	diagram: {
		type: String,
		default: null,
	},
});

const router = useRouter();
const route = useRoute();

const editorRef = ref(null);
const processName = ref("");
const processStatus = ref("");
const diagrams = ref([]);
const openTabs = ref([]);
const activeDiagramName = ref(null);
const saving = ref(false);
const creating = ref(false);
const importing = ref(false);
const editorReady = ref(false);
const hasUnsavedChanges = ref(false);
const loading = ref(true);
const showShapeLibrary = ref(false);
const showFileMenu = ref(false);


// Import file input ref
const importFileInput = ref(null);

// Auto-save state
const saveState = ref("idle"); // idle, unsaved, saving, saved, error
let saveTimeout = null;
let hasPendingSave = false; // true while the 1.5s debounce timer is counting down

// Returns true when there are edits that haven't reached the server yet
// (the debounce timer is ticking, a save is in-flight, or a save failed).
function isUnsavedOrInFlight() {
	return hasPendingSave || hasUnsavedChanges.value || saving.value;
}

const saveStatusText = computed(() => {
	switch (saveState.value) {
		case "unsaved": return "Unsaved changes";
		case "saving": return "Saving...";
		case "saved": return "Saved";
		case "error": return "Save Error";
		default: return "";
	}
});

const saveStatusColor = computed(() => {
	switch (saveState.value) {
		case "unsaved": return "text-orange-600";
		case "saving": return "text-blue-600";
		case "saved": return "text-green-600";
		case "error": return "text-red-600";
		default: return "text-transparent";
	}
});

// Notification state
const notification = ref({
	show: false,
	title: "",
	message: "",
	theme: "green"
});

// Navigation Warning Dialog state
const showUnsavedNavigationWarning = ref(false);
let pendingNavigationNext = null;

// New diagram dialog
const showNewDiagramDialog = ref(false);
const newDiagramName = ref("");
const newDiagramDescription = ref("");

// Track loaded diagram data
const diagramDataCache = ref({});

// Script Editor state
const showScriptEditorDialog = ref(false);
const scriptEditorTitle = ref("Link Server Script");
const scriptDialogMode = ref("select"); // 'select' or 'create'
const serverScripts = ref([]);
const serverScriptSearch = ref("");
const selectedServerScript = ref(null);
const loadingScripts = ref(false);
const creatingScript = ref(false);
const doctypeOptions = ref([]);
const moduleOptions = ref([]);
const doctypeSearch = ref("");
const moduleSearch = ref("");
const showDoctypeDropdown = ref(false);
const showModuleDropdown = ref(false);
let activeScriptEvent = null;
const isScriptTaskElement = ref(false);

// New Script form state
const newScript = ref({
	name: "",
	script_type: "",
	script: "",
	reference_doctype: "",
	doctype_event: "",
	api_method: "",
	allow_guest: false,
	event_frequency: "",
	cron_format: "",
	module: "",
});

// Options for select fields
const doctypeEvents = [
	"Before Insert", "Before Validate", "Before Save", "After Insert",
	"After Save", "Before Rename", "After Rename", "Before Submit",
	"After Submit", "Before Cancel", "After Cancel", "Before Delete",
	"After Delete", "Before Save (Submitted Document)",
	"After Save (Submitted Document)", "Before Print", "On Payment Authorization",
];
const eventFrequencies = [
	"All", "Hourly", "Daily", "Weekly", "Monthly", "Yearly",
	"Hourly Long", "Daily Long", "Weekly Long", "Monthly Long", "Cron",
];

// Computed: filtered scripts based on search (restricted to API for Script Tasks)
const filteredServerScripts = computed(() => {
	let list = serverScripts.value;
	// Script Task elements can only use API-type server scripts
	if (isScriptTaskElement.value) {
		list = list.filter((s) => s.script_type === "API");
	}
	if (!serverScriptSearch.value) return list;
	const q = serverScriptSearch.value.toLowerCase();
	return list.filter(
		(s) =>
			s.name.toLowerCase().includes(q) ||
			(s.script_type && s.script_type.toLowerCase().includes(q)) ||
			(s.reference_doctype && s.reference_doctype.toLowerCase().includes(q))
	);
});

// Computed: filtered DocType options based on search
const filteredDoctypeOptions = computed(() => {
	if (!doctypeSearch.value) return doctypeOptions.value.slice(0, 50);
	const q = doctypeSearch.value.toLowerCase();
	return doctypeOptions.value.filter((dt) => dt.toLowerCase().includes(q)).slice(0, 50);
});

// Computed: filtered Module options based on search
const filteredModuleOptions = computed(() => {
	if (!moduleSearch.value) return moduleOptions.value.slice(0, 50);
	const q = moduleSearch.value.toLowerCase();
	return moduleOptions.value.filter((m) => m.toLowerCase().includes(q)).slice(0, 50);
});

// Markdown Editor state
const showMarkdownEditorDialog = ref(false);
const markdownEditorContent = ref("");
let activeMarkdownEvent = null;

// Call Activity Search state
const showCallActivitySearchDialog = ref(false);
let callActivitySearchEvent = null; // plain variable — NOT a ref, because bpmn-js
// element objects have non-configurable/frozen properties (e.g. 'labels') that
// conflict with Vue 3's Proxy-based reactivity and cause TypeErrors.


// Zoom level (synced with BpmnEditor)
const zoomLevel = computed(() => currentZoomLevel.value);

// Zoom handlers
const currentZoomLevel = ref(100);

function handleZoomIn() {
	if (editorRef.value) {
		editorRef.value.zoomIn();
		updateZoomLevel();
	}
}

function handleZoomOut() {
	if (editorRef.value) {
		editorRef.value.zoomOut();
		updateZoomLevel();
	}
}

function handleResetZoom() {
	if (editorRef.value) {
		editorRef.value.resetZoom();
		updateZoomLevel();
	}
}

function handleFitToScreen() {
	if (editorRef.value) {
		editorRef.value.fitToScreen();
		// Wait for async zoom update
		setTimeout(() => updateZoomLevel(), 10);
	}
}

function updateZoomLevel() {
	if (editorRef.value && typeof editorRef.value.getZoomLevel === 'function') {
		currentZoomLevel.value = editorRef.value.getZoomLevel();
	}
}

function onZoomChanged(newZoom) {
	currentZoomLevel.value = newZoom;
}

// Shape library handler
function onShapeDragStart(shape) {
	console.log("Shape drag started:", shape.shape_name);
	// The actual drop handling will be done by bpmn-js canvas
}

// Keyboard shortcut handler
function handleKeyDown(event) {
	// Ctrl+S or Cmd+S to save
	if ((event.ctrlKey || event.metaKey) && event.key === "s") {
		event.preventDefault();
		if (activeDiagramName.value && !saving.value) {
			saveCurrentDiagram();
		}
	}
	// Ctrl++ or Ctrl+= to zoom in
	if ((event.ctrlKey || event.metaKey) && (event.key === "+" || event.key === "=")) {
		event.preventDefault();
		handleZoomIn();
	}
	// Ctrl+- to zoom out
	if ((event.ctrlKey || event.metaKey) && event.key === "-") {
		event.preventDefault();
		handleZoomOut();
	}
	// Ctrl+0 to reset zoom
	if ((event.ctrlKey || event.metaKey) && event.key === "0") {
		event.preventDefault();
		handleResetZoom();
	}
}

function handleBeforeUnload(event) {
	// Guard fires when: edits are pending (debounce ticking), a save is in-flight, OR
	// a previous save failed and changes remain unsaved.
	if (isUnsavedOrInFlight()) {
		event.preventDefault();
		// returnValue must be set for Firefox; modern Chrome ignores the string.
		event.returnValue = "";
	}
}

// Prevent accidental navigation (clicking Back / going to a different Vue route)
onBeforeRouteLeave((to, from, next) => {
	if (isUnsavedOrInFlight()) {
		showUnsavedNavigationWarning.value = true;
		pendingNavigationNext = next;
	} else {
		next();
	}
});

function confirmNavigation() {
	showUnsavedNavigationWarning.value = false;
	if (pendingNavigationNext) {
		pendingNavigationNext(); // allow the route change to proceed
		pendingNavigationNext = null;
	}
}

function cancelNavigation() {
	showUnsavedNavigationWarning.value = false;
	if (pendingNavigationNext) {
		pendingNavigationNext(false); // block the route change
		pendingNavigationNext = null;
	}
}

onMounted(async () => {
	// Add keyboard shortcut listener
	window.addEventListener("keydown", handleKeyDown);
	window.addEventListener("beforeunload", handleBeforeUnload);

	try {
		loading.value = true;
		await loadProcess();

		// Add all diagrams to open tabs
		if (diagrams.value.length > 0) {
			openTabs.value = [...diagrams.value];
		}

		// If a specific diagram was passed in route, select it
		if (props.diagram) {
			activeDiagramName.value = props.diagram;
		} else if (diagrams.value.length > 0) {
			// Select first diagram by default
			activeDiagramName.value = diagrams.value[0].name;
		}
	} finally {
		loading.value = false;
	}
});

onUnmounted(() => {
	// Remove listeners
	window.removeEventListener("keydown", handleKeyDown);
	window.removeEventListener("beforeunload", handleBeforeUnload);
	clearTimeout(saveTimeout);
});

async function loadProcess() {
	try {
		const response = await frappeRequest({
			url: "/api/method/one_bpmn.api.get_process_diagrams",
			params: { process: props.process },
		});

		const data = response.message || response;
		processName.value = data.process_name;
		diagrams.value = data.diagrams || [];

		// Derive status from most recent diagram
		if (diagrams.value.length > 0) {
			processStatus.value = diagrams.value[0].status;
		}
	} catch (error) {
		console.error("Failed to load process:", error);
	}
}

async function selectDiagram(name) {
	if (activeDiagramName.value === name) return;

	// Save current diagram if there are unsaved changes
	if (hasUnsavedChanges.value && activeDiagramName.value && editorRef.value) {
		clearTimeout(saveTimeout);
		saving.value = true;
		await saveCurrentDiagram();
	}

	activeDiagramName.value = name;

	// Add to open tabs if not already there
	if (!openTabs.value.find((t) => t.name === name)) {
		const diagram = diagrams.value.find((d) => d.name === name);
		if (diagram) {
			openTabs.value.push(diagram);
		}
	}

	// Update URL
	router.replace({
		name: "DiagramEditor",
		params: { process: props.process, diagram: name },
	});
	// The watch(activeDiagramName) handles loading the new diagram XML.
}

async function onEditorReady() {
	editorReady.value = true;

	// Load the initial diagram content (fires only once on first mount)
	if (activeDiagramName.value) {
		await loadDiagramContent(activeDiagramName.value);
		hasUnsavedChanges.value = false;
	}

	hasUnsavedChanges.value = false;
	saveState.value = 'saved';
}

// Watch for diagram tab switches and load new XML without remounting the editor.
watch(activeDiagramName, async (newName) => {
	if (!editorReady.value || !newName) return;
	hasUnsavedChanges.value = false;
	saveState.value = 'saved';
	await loadDiagramContent(newName);
	hasUnsavedChanges.value = false;
});

async function loadDiagramContent(name) {
	// Check cache first
	if (diagramDataCache.value[name]) {
		if (editorRef.value) {
			await editorRef.value.loadXML(diagramDataCache.value[name]);
		}
		return;
	}

	try {
		const response = await frappeRequest({
			url: "/api/method/one_bpmn.api.get_process_model",
			params: { name },
		});

		const data = response.message || response;
		if (data && data.xml_content && editorRef.value) {
			diagramDataCache.value[name] = data.xml_content;
			await editorRef.value.loadXML(data.xml_content);
		}
	} catch (error) {
		console.error("Failed to load diagram:", error);
	}
}

async function saveDiagramToCache(name) {
	if (editorRef.value) {
		const xml = await editorRef.value.getXML();
		diagramDataCache.value[name] = xml;
	}
}

function onDiagramChanged() {
	if (!editorReady.value) return;

	hasUnsavedChanges.value = true;
	saveState.value = 'unsaved';

	clearTimeout(saveTimeout);
	hasPendingSave = true;
	saveTimeout = setTimeout(() => {
		hasPendingSave = false;
		if (activeDiagramName.value) {
			saveCurrentDiagram();
		}
	}, 1500);
}

async function saveCurrentDiagram() {
	if (!activeDiagramName.value || !editorRef.value) return;

	saving.value = true;
	saveState.value = 'saving';
	try {
		const xml = await editorRef.value.getXML();
		const diagram = diagrams.value.find((d) => d.name === activeDiagramName.value);

		// Use JSON body for Frappe API
		const response = await fetch("/api/method/one_bpmn.api.save_process_model", {
			method: "POST",
			headers: {
				"Content-Type": "application/json",
				"X-Frappe-CSRF-Token": window.csrf_token || "",
			},
			body: JSON.stringify({
				process: props.process,
				model_name: diagram.model_name,
				xml_content: xml,
				description: diagram.description || "",
			}),
		});

		const data = await response.json();
		if (data.exc) {
			throw new Error(data.exc);
		}

		hasUnsavedChanges.value = false;
		diagramDataCache.value[activeDiagramName.value] = xml;
		
		saveState.value = 'saved';
	} catch (error) {
		console.error("Failed to save diagram:", error);
		saveState.value = 'error';
		showNotification("Error", "Failed to save: " + (error.message || error), "red");
	} finally {
		saving.value = false;
	}
}

function showNotification(title, message, theme = "green") {
	notification.value = {
		show: true,
		title,
		message,
		theme
	};
	// Auto-hide after 3 seconds
	setTimeout(() => {
		notification.value.show = false;
	}, 3000);
}

function showAddDiagramDialog() {
	newDiagramName.value = "";
	newDiagramDescription.value = "";
	showNewDiagramDialog.value = true;
}

async function createDiagram() {
	if (!newDiagramName.value.trim()) {
		alert("Please enter a diagram name");
		return;
	}

	creating.value = true;
	try {
		// Create with empty diagram
		const emptyXml = `<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
                  xmlns:bpmndi="http://www.omg.org/spec/BPMN/20100524/DI"
                  xmlns:dc="http://www.omg.org/spec/DD/20100524/DC"
                  id="Definitions_1"
                  targetNamespace="http://bpmn.io/schema/bpmn">
  <bpmn:process id="Process_1" isExecutable="true">
    <bpmn:startEvent id="StartEvent_1" />
  </bpmn:process>
  <bpmndi:BPMNDiagram id="BPMNDiagram_1">
    <bpmndi:BPMNPlane id="BPMNPlane_1" bpmnElement="Process_1">
      <bpmndi:BPMNShape id="_BPMNShape_StartEvent_1" bpmnElement="StartEvent_1">
        <dc:Bounds x="173" y="102" width="36" height="36" />
      </bpmndi:BPMNShape>
    </bpmndi:BPMNPlane>
  </bpmndi:BPMNDiagram>
</bpmn:definitions>`;

		// Use JSON body for Frappe API
		const response = await fetch("/api/method/one_bpmn.api.save_process_model", {
			method: "POST",
			headers: {
				"Content-Type": "application/json",
				"X-Frappe-CSRF-Token": window.csrf_token || "",
			},
			body: JSON.stringify({
				process: props.process,
				model_name: newDiagramName.value,
				xml_content: emptyXml,
				description: newDiagramDescription.value || "",
			}),
		});

		const data = await response.json();
		if (data.exc) {
			throw new Error(data.exc);
		}

		const result = data.message || data;
		showNewDiagramDialog.value = false;

		// Reload process and open new diagram
		await loadProcess();
		selectDiagram(result.name);
	} catch (error) {
		console.error("Failed to create diagram:", error);
		alert("Failed to create: " + (error.message || error));
	} finally {
		creating.value = false;
	}
}

async function closeTab(name) {
	// If closing the active tab with pending changes, save silently first
	if (activeDiagramName.value === name && isUnsavedOrInFlight()) {
		clearTimeout(saveTimeout);
		hasPendingSave = false;
		await saveCurrentDiagram();
	}

	const index = openTabs.value.findIndex((t) => t.name === name);
	if (index > -1) {
		openTabs.value.splice(index, 1);

		// If closing active tab, switch to another
		if (activeDiagramName.value === name) {
			if (openTabs.value.length > 0) {
				const newIndex = Math.min(index, openTabs.value.length - 1);
				selectDiagram(openTabs.value[newIndex].name);
			} else {
				activeDiagramName.value = null;
			}
		}
	}
}

/**
 * Apply field updates to matching entries in both diagrams and openTabs.
 * Keeps the update/revert logic in one place (Review #2).
 */
function applyTabDiagramFields(matchName, fields) {
	const diagramEntry = diagrams.value.find((d) => d.name === matchName);
	const tabEntry = openTabs.value.find((t) => t.name === matchName);
	if (diagramEntry) Object.assign(diagramEntry, fields);
	if (tabEntry) Object.assign(tabEntry, fields);
}

async function renameProcessModel({ tabName, oldModelName, newModelName }) {
	// --- Review #1: Flush pending autosave before renaming ---
	// Cancel the debounce timer so autosave can't fire with a stale model_name.
	clearTimeout(saveTimeout);
	hasPendingSave = false;

	// If there are unsaved diagram changes, flush them under the OLD name first.
	if (hasUnsavedChanges.value && activeDiagramName.value === tabName && editorRef.value) {
		await saveCurrentDiagram();
	}

	try {
		const response = await frappeRequest({
			url: "/api/method/one_bpmn.api.rename_process_model",
			params: {
				name: tabName,
				new_title: newModelName,
			},
		});

		const result = response.message || response;
		const newName = result.name;
		const actualModelName = result.model_name;

		// Transfer cached XML to new key
		if (diagramDataCache.value[tabName]) {
			diagramDataCache.value[newName] = diagramDataCache.value[tabName];
			if (newName !== tabName) {
				delete diagramDataCache.value[tabName];
			}
		}

		// Apply name + display fields after API success (avoids autosave race)
		applyTabDiagramFields(tabName, {
			name: newName,
			model_name: actualModelName,
			title: actualModelName,
		});

		// Update active diagram ref and URL if the renamed tab is active
		if (activeDiagramName.value === tabName) {
			activeDiagramName.value = newName;
			router.replace({
				name: "DiagramEditor",
				params: { process: props.process, diagram: newName },
			});
		}

		showNotification("Renamed", `Diagram renamed to "${actualModelName}"`, "green");
	} catch (error) {
		console.error("Failed to rename process model:", error);
		showNotification(
			"Rename Failed",
			error.message || error._server_messages || "An error occurred while renaming.",
			"red"
		);
	}
}

function goBack() {
	router.push({ name: "Home" });
}

async function exportCurrentDiagram() {
	if (!activeDiagramName.value || !editorRef.value) return;

	try {
		const xml = await editorRef.value.getXML();
		const diagram = diagrams.value.find((d) => d.name === activeDiagramName.value);
		const title = diagram?.model_name || activeDiagramName.value;
		const filename = downloadBpmn(xml, title);
		showNotification("Exported", `Downloaded as ${filename}`, "green");
	} catch (error) {
		console.error("Failed to export diagram:", error);
		showNotification("Error", "Failed to export diagram", "red");
	}
}

function triggerImport() {
	if (importFileInput.value) {
		// Reset so the same file can be re-imported
		importFileInput.value.value = "";
		importFileInput.value.click();
	}
}

async function handleImportFile(event) {
	const file = event.target.files && event.target.files[0];
	if (!file) return;

	importing.value = true;
	try {
		// Read the file as text
		const xmlContent = await new Promise((resolve, reject) => {
			const reader = new FileReader();
			reader.onload = (e) => resolve(e.target.result);
			reader.onerror = () => reject(new Error("Failed to read file"));
			reader.readAsText(file);
		});

		// Call the backend import endpoint via frappeRequest for consistent
		// CSRF handling, response parsing, and error surfacing.
		const result = await frappeRequest({
			url: "/api/method/one_bpmn.api.import_bpmn",
			method: "POST",
			params: {
				xml_content: xmlContent,
				// Use the filename (minus .bpmn) as the human-readable title
				title: file.name.replace(/\.bpmn$/i, ""),
				process: props.process || undefined,
			},
		});

		const action = result.action === "updated" ? "updated" : "imported";

		// Pre-populate cache so the watch(activeDiagramName) handler
		// gets an instant cache-hit and calls loadXML without a round-trip.
		diagramDataCache.value[result.name] = xmlContent;

		// Reload process diagrams to sync the diagrams list
		await loadProcess();
		let diagramEntry = diagrams.value.find((d) => d.name === result.name);
		if (!diagramEntry) {
			// Not in the process-scoped list — add a synthetic entry so the tab appears
			diagramEntry = {
				name: result.name,
				model_name: result.model_name,
				title: result.model_name,
				process_id: result.process_id,
				status: "Active",
			};
			diagrams.value.push(diagramEntry);
		}

		// Preserve existing openTabs; only add the imported diagram tab if not already open
		if (!openTabs.value.some((tab) => tab.name === diagramEntry.name)) {
			openTabs.value = [...openTabs.value, diagramEntry];
		}

		// Switch to the imported diagram via SPA (no page reload → no Preact crash)
		// The watch(activeDiagramName) picks up the change and calls loadDiagramContent.
		activeDiagramName.value = result.name;
		router.replace({
			name: "DiagramEditor",
			params: { process: props.process, diagram: result.name },
		});

		showNotification(
			"Import Successful",
			`Diagram "${result.model_name}" ${action} successfully.`,
			"green"
		);
	} catch (error) {
		console.error("Import failed:", error);
		showNotification(
			"Import Failed",
			error.message || "An unexpected error occurred while importing.",
			"red"
		);
	} finally {
		importing.value = false;
	}
}

function getStatusTheme(status) {
	switch (status) {
		case "Published":
			return "green";
		case "In Development":
			return "orange";
		case "Draft":
			return "blue";
		default:
			return "gray";
	}
}

// --- SpiffWorkflow Editor Handlers ---

async function onLaunchScriptEditor(event) {
	activeScriptEvent = event;

	// Determine title based on script type
	const typeLabels = {
		"bpmn:script": "Link Server Script",
		"spiffworkflow:PreScript": "Link Pre-Script to Server Script",
		"spiffworkflow:PostScript": "Link Post-Script to Server Script",
	};
	scriptEditorTitle.value = typeLabels[event.scriptType] || "Link Server Script";

	// Reset dialog state
	scriptDialogMode.value = "select";
	serverScriptSearch.value = "";
	selectedServerScript.value = event.script || null; // Pre-select if already linked
	doctypeSearch.value = "";
	moduleSearch.value = "";
	showDoctypeDropdown.value = false;
	showModuleDropdown.value = false;
	// Set reactive flag for Script Task restriction
	const isScriptTask = event.element && event.element.type === "bpmn:ScriptTask";
	isScriptTaskElement.value = isScriptTask;
	newScript.value = {
		name: "", script_type: isScriptTask ? "API" : "", script: "", reference_doctype: "",
		doctype_event: "", api_method: "", allow_guest: false,
		event_frequency: "", cron_format: "", module: "",
	};

	// Fetch server scripts
	loadingScripts.value = true;
	showScriptEditorDialog.value = true;

	try {
		const response = await fetch(
			"/api/resource/Server Script?fields=[\"name\",\"script_type\",\"reference_doctype\",\"disabled\",\"module\",\"modified\"]&limit_page_length=0&order_by=modified%20desc",
			{ headers: { "X-Frappe-CSRF-Token": window.csrf_token || "" } }
		);
		const json = await response.json();
		serverScripts.value = Array.isArray(json.data) ? json.data : [];
	} catch (error) {
		console.error("Failed to load server scripts:", error);
		serverScripts.value = [];
	} finally {
		loadingScripts.value = false;
	}

	// Fetch DocTypes and Modules for create form dropdowns
	if (doctypeOptions.value.length === 0) {
		try {
			const dtResp = await frappeRequest({
				url: "/api/method/frappe.client.get_list",
				params: { doctype: "DocType", fields: ["name"], limit_page_length: 0, order_by: "name asc" },
			});
			doctypeOptions.value = (dtResp.message || dtResp || []).map((d) => d.name);
		} catch (e) {
			console.error("Failed to load DocTypes:", e);
		}
	}
	if (moduleOptions.value.length === 0) {
		try {
			const modResp = await frappeRequest({
				url: "/api/method/frappe.client.get_list",
				params: { doctype: "Module Def", fields: ["name"], limit_page_length: 0, order_by: "name asc" },
			});
			moduleOptions.value = (modResp.message || modResp || []).map((m) => m.name);
		} catch (e) {
			console.error("Failed to load Modules:", e);
		}
	}
}

function saveScript() {
	// "Select Existing" mode — write the selected Server Script name
	if (activeScriptEvent && activeScriptEvent.eventBus && selectedServerScript.value) {
		activeScriptEvent.eventBus.fire("spiff.script.update", {
			element: activeScriptEvent.element,
			scriptType: activeScriptEvent.scriptType,
			script: selectedServerScript.value,
		});
	}
	showScriptEditorDialog.value = false;
	activeScriptEvent = null;
}

async function createAndLinkScript() {
	// "Create New" mode — create Server Script then link it
	if (!newScript.value.name || !newScript.value.script_type || !newScript.value.script) {
		showNotification("Validation", "Script name, type, and content are required.", "red");
		return;
	}

	creatingScript.value = true;
	try {
		const result = await frappeRequest({
			url: "one_bpmn.api.create_server_script",
			params: {
				script_name: newScript.value.name,
				script_type: newScript.value.script_type,
				script: newScript.value.script,
				...(newScript.value.reference_doctype && { reference_doctype: newScript.value.reference_doctype }),
				...(newScript.value.doctype_event && { doctype_event: newScript.value.doctype_event }),
				...(newScript.value.api_method && { api_method: newScript.value.api_method }),
				...(newScript.value.allow_guest && { allow_guest: 1 }),
				...(newScript.value.event_frequency && { event_frequency: newScript.value.event_frequency }),
				...(newScript.value.cron_format && { cron_format: newScript.value.cron_format }),
				...(newScript.value.module && { module: newScript.value.module }),
			},
		});

		// Write the new script's name back to the BPMN element
		if (activeScriptEvent && activeScriptEvent.eventBus) {
			activeScriptEvent.eventBus.fire("spiff.script.update", {
				element: activeScriptEvent.element,
				scriptType: activeScriptEvent.scriptType,
				script: result.name,
			});
		}

		showNotification("Success", `Server Script "${result.name}" created and linked.`, "green");
		showScriptEditorDialog.value = false;
		activeScriptEvent = null;
	} catch (error) {
		console.error("Failed to create server script:", error);
		showNotification("Error", "Failed to create: " + (error.message || error), "red");
	} finally {
		creatingScript.value = false;
	}
}

function onLaunchMarkdownEditor(event) {
	activeMarkdownEvent = event;
	markdownEditorContent.value = event.value || "";
	showMarkdownEditorDialog.value = true;
}

function saveMarkdown() {
	if (activeMarkdownEvent && activeMarkdownEvent.eventBus) {
		activeMarkdownEvent.eventBus.fire("spiff.markdown.update", {
			element: activeMarkdownEvent.element,
			value: markdownEditorContent.value,
		});
	}
	showMarkdownEditorDialog.value = false;
	activeMarkdownEvent = null;
}

async function onLaunchCallActivityEditor(event) {
	if (!event.processId) {
		showNotification(
			"Call Activity",
			"No process linked. Use the Search button to select a process first.",
			"orange"
		);
		return;
	}

	try {
		// Use the dedicated resolve endpoint — returns one record without
		// fetching the entire model list client-side.
		const response = await frappeRequest({
			url: "/api/method/one_bpmn.api.resolve_process_model_by_id",
			params: { process_id: event.processId },
		});
		const linked = response.message || response;

		if (linked && linked.name) {
			// Build URL with encoded segments to handle spaces and reserved chars
			const base = linked.process_name
				? `/processa/process/${encodeURIComponent(linked.process_name)}/diagram/${encodeURIComponent(linked.name)}`
				: `/processa/process/${encodeURIComponent(linked.name)}`;
			// noopener,noreferrer prevents reverse-tabnabbing via window.opener
			window.open(base, "_blank", "noopener,noreferrer");
		} else {
			showNotification(
				"Call Activity",
				`Linked process "${event.processId}" not found in this system.`,
				"orange"
			);
		}
	} catch (err) {
		showNotification("Call Activity", "Failed to look up linked process.", "red");
	}
}

function onLaunchCallActivitySearch(event) {
	callActivitySearchEvent = event;
	showCallActivitySearchDialog.value = true;
}

function onCallActivitySelected(processId) {
	const event = callActivitySearchEvent;
	if (!event) return;

	// Primary: drive the update directly via the modeler's command stack.
	// Reliable regardless of SpiffWorkflow's async once-listener state.
	if (editorRef.value && typeof editorRef.value.updateCalledElement === "function") {
		editorRef.value.updateCalledElement(event.element, processId);
	}

	// Secondary: also fire spiff.callactivity.update so the once-listener (if still
	// active) can run its own commandStack path.
	if (event.eventBus) {
		event.eventBus.fire("spiff.callactivity.update", {
			element: event.element,
			value: processId,
		});
	}

	showCallActivitySearchDialog.value = false;
	callActivitySearchEvent = null;
}

function onCancelCallActivitySearch() {
	// Mirror the select path: close dialog AND clear the stored event reference
	// so we don't retain stale BPMN element/eventBus objects.
	showCallActivitySearchDialog.value = false;
	callActivitySearchEvent = null;
}
</script>

<style scoped>
/* Fix dark background on form inputs in dialog */
:deep(.dialog-form input),
:deep(.dialog-form textarea),
:deep(.dialog-body input[type="text"]),
:deep(.dialog-body textarea) {
	background-color: white !important;
	color: #1f2937 !important;
}

/* Force TextEditor to fill full dialog width */
:deep(.ProseMirror) {
	max-width: 100% !important;
	width: 100% !important;
}

:deep(.tiptap) {
	max-width: 100% !important;
	width: 100% !important;
}
</style>
