<template>
	<div class="h-full flex flex-col">
		<!-- Header -->
		<header class="bg-gray-200 border-b px-4 py-3 flex items-center justify-between">
			<div class="flex items-center gap-4">
				<button
					@click="goBack"
					class="p-2 hover:bg-gray-100 rounded-md transition-colors"
					title="Back to list"
				>
					<Icon icon="lucide:chevron-left" class="w-5 h-5" />
				</button>
				<div class="flex items-center gap-3">
					<h1 class="text-lg font-semibold text-gray-900">{{ processName }}</h1>
					<Badge v-if="processStatus" :theme="getStatusTheme(processStatus)" :label="processStatus" />
				</div>
			</div>
			<div v-if="activeDiagramName" class="flex items-center gap-2">
				<Button variant="solid" class="p-2 hover:bg-gray-100 rounded-md transition-colors" @click="saveCurrentDiagram" :loading="saving">
					Save
				</Button>
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

					<BpmnEditor
						v-else-if="activeDiagramName"
						ref="editorRef"
						:key="activeDiagramName"
						class="absolute inset-0"
						@ready="onEditorReady"
						@changed="onDiagramChanged"
						@zoom-changed="onZoomChanged"
						@launch-script-editor="onLaunchScriptEditor"
						@launch-markdown-editor="onLaunchMarkdownEditor"
						@launch-callactivity-editor="onLaunchCallActivityEditor"
					/>
					<div v-else class="flex items-center justify-center h-full bg-gray-100">
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

			<!-- Tab Bar with Zoom Controls -->
			<div v-if="openTabs.length > 0" class="flex items-center bg-gray-200 border-t border-gray-300">
				<EditorTabs
					:tabs="openTabs"
					:activeTab="activeDiagramName"
					@select-tab="selectDiagram"
					@add-tab="showAddDiagramDialog"
					class="flex-1"
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
								>
									<option value="">Select type...</option>
									<option value="DocType Event">DocType Event</option>
									<option value="Scheduler Event">Scheduler Event</option>
									<option value="Permission Query">Permission Query</option>
									<option value="API">API</option>
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
	</div>
</template>

<script setup>
import { ref, onMounted, onUnmounted, computed, watch } from "vue";
import { useRouter, useRoute } from "vue-router";
import { frappeRequest, TextEditor } from "frappe-ui";
import { Icon } from "@iconify/vue";
import BpmnEditor from "@/components/BpmnEditor.vue";
import EditorTabs from "@/components/EditorTabs.vue";
import ShapeLibraryPanel from "@/components/ShapeLibraryPanel.vue";

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
const editorReady = ref(false);
const hasUnsavedChanges = ref(false);
const loading = ref(true);
const showShapeLibrary = ref(false);

// Notification state
const notification = ref({
	show: false,
	title: "",
	message: "",
	theme: "green"
});

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

// Computed: filtered scripts based on search
const filteredServerScripts = computed(() => {
	if (!serverScriptSearch.value) return serverScripts.value;
	const q = serverScriptSearch.value.toLowerCase();
	return serverScripts.value.filter(
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

onMounted(async () => {
	// Add keyboard shortcut listener
	window.addEventListener("keydown", handleKeyDown);

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
	// Remove keyboard shortcut listener
	window.removeEventListener("keydown", handleKeyDown);
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
	// Save current diagram if there are unsaved changes
	if (hasUnsavedChanges.value && activeDiagramName.value && editorRef.value) {
		await saveDiagramToCache(activeDiagramName.value);
	}

	activeDiagramName.value = name;

	// Add to open tabs if not already there
	if (!openTabs.value.find((t) => t.name === name)) {
		const diagram = diagrams.value.find((d) => d.name === name);
		if (diagram) {
			openTabs.value.push(diagram);
		}
	}

	// Load diagram data
	editorReady.value = false;

	// Update URL
	router.replace({
		name: "DiagramEditor",
		params: { process: props.process, diagram: name },
	});
}

async function onEditorReady() {
	editorReady.value = true;

	// Load diagram content
	if (activeDiagramName.value) {
		await loadDiagramContent(activeDiagramName.value);
	}

	hasUnsavedChanges.value = false;
}

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
	hasUnsavedChanges.value = true;
}

async function saveCurrentDiagram() {
	if (!activeDiagramName.value || !editorRef.value) return;

	saving.value = true;
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
	} catch (error) {
		console.error("Failed to save diagram:", error);
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

function closeTab(name) {
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

function goBack() {
	router.push({ name: "Home" });
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
	newScript.value = {
		name: "", script_type: "", script: "", reference_doctype: "",
		doctype_event: "", api_method: "", allow_guest: false,
		event_frequency: "", cron_format: "", module: "",
	};

	// Fetch server scripts
	loadingScripts.value = true;
	showScriptEditorDialog.value = true;

	try {
		const response = await frappeRequest({
			url: "/api/method/one_bpmn.api.list_server_scripts",
		});
		serverScripts.value = response.message || response || [];
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
		const payload = {
			script_name: newScript.value.name,
			script_type: newScript.value.script_type,
			script: newScript.value.script,
		};
		if (newScript.value.reference_doctype) payload.reference_doctype = newScript.value.reference_doctype;
		if (newScript.value.doctype_event) payload.doctype_event = newScript.value.doctype_event;
		if (newScript.value.api_method) payload.api_method = newScript.value.api_method;
		if (newScript.value.allow_guest) payload.allow_guest = 1;
		if (newScript.value.event_frequency) payload.event_frequency = newScript.value.event_frequency;
		if (newScript.value.cron_format) payload.cron_format = newScript.value.cron_format;
		if (newScript.value.module) payload.module = newScript.value.module;

		const response = await fetch("/api/method/one_bpmn.api.create_server_script", {
			method: "POST",
			headers: {
				"Content-Type": "application/json",
				"X-Frappe-CSRF-Token": window.csrf_token || "",
			},
			body: JSON.stringify(payload),
		});

		const data = await response.json();
		if (data.exc) {
			throw new Error(data.exc);
		}

		const result = data.message || data;

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

function onLaunchCallActivityEditor(event) {
	console.log("Call Activity editor requested for process:", event.processId);
	showNotification(
		"Call Activity",
		`Process ID: ${event.processId}. Full editor integration coming soon.`,
		"blue"
	);
}
</script>

<style scoped>
/* Fix dark background on form inputs in dialog */
:deep(.dialog-form input),
:deep(.dialog-form textarea),
:deep(input[type="text"]),
:deep(textarea) {
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
