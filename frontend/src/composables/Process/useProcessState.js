import { provide, ref } from "vue";
import { useRoute, useRouter } from "vue-router";
import { useNotificationDialog } from "@/composables/useNotificationDialog";
import { useWindowSize } from "@/composables/useWindowSize";

export const PROCESS_KEY = Symbol("processPage");

export function createProcessContext(props) {
	const router = useRouter();
	const route = useRoute();
	const { isMobile } = useWindowSize();

	// Compact mode: diagram dropdown state
	const showCompactDiagramMenu = ref(false);

	const otherEditors = ref([]);

	const editorRef = ref(null);

	const processName = ref("");

	const diagrams = ref([]);

	const openTabs = ref([]);

	const activeDiagramName = ref("");

	// --- Lifecycle ---
	const saving = ref(false);

	const importing = ref(false);

	const editorReady = ref(false);

	const hasUnsavedChanges = ref(false);

	const loading = ref(true);

	const showFileMenu = ref(false);

	const showStatusPopup = ref(false);

	const showMobileMoreMenu = ref(false);

	const deploying = ref(false);

	const disabling = ref(false);

	const showDisableDialog = ref(false);

	const disableRunningCount = ref(0);

	const showNonExecutableDialog = ref(false);

	const nonExecutableActivating = ref(true);

	const nonExecutableBusy = ref(false);

	// --- Actions menu + Production Review state ---
	const showActionsMenu = ref(false);

	// Whether Processa Settings has "Connect to Production" enabled.
	const connectToProduction = ref(false);

	// Processa Settings → Instance Type. Gates the environment-specific Actions:
	// "Review Doctypes" / "Review Workflow Objects" → BA instance only
	// "Release Property Panel"                      → Production instance only
	const instanceType = ref("");

	const showReviewDialog = ref(false);

	const reviewKind = ref("doctypes"); // "doctypes" | "workflow"

	// A doctype sync raises a pull request; only a workflow sync writes to Production itself.
	const prBaseBranch = ref("");

	const reviewStage = ref("intro"); // intro | loading | diff | empty | syncing | result

	const reviewChanges = ref([]);

	const reviewResult = ref(null);

	// --- Release Property Panel (only on a Production instance) ---
	// While released, the properties panel can edit flow objects on an otherwise
	// read-only canvas - everything except script tasks, AI Agent tasks, sequence
	// flows and the attributes that would break the map (see
	// processa/api/property_panel.py). Each change is persisted through that
	// endpoint, because the normal save path is blocked on locked models. The map
	// is recompiled ONCE - a single Deploy - when the panel is locked again.
	const reassignMode = ref(false);

	const pendingReassignments = new Map(); // taskId → { modelName, assignment }

	// Models actually changed this session, awaiting the batched deploy. This used
	// to carry audit-log names too; the log is gone, but the set still decides
	// whether to deploy at all and which maps to recompile.
	const touchedReassignModels = new Set(); // modelName

	// --- DMN Editor State ---
	const showDmnEditorDialog = ref(false);

	const dmnEditorRef = ref(null);

	const dmnEditorTitle = ref("Edit Decision Model");

	const dmnEditorXml = ref("");

	const dmnEditorKey = ref(0); // Incremented on each open to force full recreation

	// True when the current diagram's BPMN process is marked as executable
	const isExecutable = ref(false);

	// Readiness checklist state
	const showReadinessDialog = ref(false);

	const readinessChecklist = ref(null);

	const readinessMode = ref("import"); // "import" or "deploy"

	const readinessLoading = ref(false);

	// Export config dialog state
	const showExportConfigDialog = ref(false);

	const exportConfigCounts = ref({
		server_scripts: 0,
		workflow_states: 0,
		workflow_action_masters: 0,
	});

	// Config import results dialog state
	const showConfigImportResults = ref(false);

	const configImportResults = ref({ created: [], skipped: [], needs_confirmation: [] });

	const configImporting = ref(false);

	// Config import file input ref
	const importConfigFileInput = ref(null);

	// Version diff dialog ref
	const versionDiffRef = ref(null);

	// Compare versions dialog ref (named version vs latest)
	const compareDialogRef = ref(null);

	// Named versions of the active map, shown as read-only chips in the bottom bar.
	const namedVersionTabs = ref([]);

	// When set (snapshot doc name), the editor is previewing a named version
	// read-only instead of editing the live map.
	const activeVersionName = ref(null);

	// Process Implementation editability state (process-level: can new maps be
	// created / does at least one editable implementation exist for the process)
	const isEditable = ref(false); // locked by default until API confirms

	const editabilityInfo = ref({
		editable: false,
		process_implementation: null,
		workflow_state: null,
		override: false,
		reason: null,
	});

	// Import file input ref
	const importFileInput = ref(null);

	// Auto-save state
	const saveState = ref("idle"); // idle, unsaved, saving, saved, error

	// Notification state
	const notification = ref({
		show: false,
		title: "",
		message: "",
		theme: "green",
	});

	// Navigation Warning Dialog state
	const showUnsavedNavigationWarning = ref(false);

	// Track loaded diagram data
	const diagramDataCache = ref({});

	// Script Editor state
	const showScriptEditorDialog = ref(false);

	const scriptEditorTitle = ref("Link Server Script");

	const scriptDialogMode = ref("select");

	const serverScripts = ref([]);

	const serverScriptSearch = ref("");

	const selectedServerScript = ref(null);

	const loadingScripts = ref(false);

	const creatingScript = ref(false);

	const showDoctypeDropdown = ref(false);

	const showModuleDropdown = ref(false);

	// Script preview state (Select Existing tab)
	const previewScriptContent = ref(null);

	const loadingPreview = ref(false);

	// Edit tab state
	const linkedScriptName = ref("");

	const editScriptContent = ref("");

	const editScriptMeta = ref({ script_type: "", reference_doctype: "" });

	const loadingEditScript = ref(false);

	const savingEditScript = ref(false);

	// New Script form state
	const newScript = ref({
		name: "",
		script_type: "API",
		script: "",
		reference_doctype: "",
		doctype_event: "",
		api_method: "",
		allow_guest: false,
		event_frequency: "",
		cron_format: "",
		module: "",
	});

	// Logix Canvas state
	const showLogixCanvas = ref(false);

	const logixElement = ref(null);

	const logixScriptType = ref("bpmn:script");

	const logixCurrentScript = ref("");

	const logixEventBus = ref(null);

	const logixProcessContext = ref(null);

	// True when the script was launched from a read-only map - the editor and
	// chat both open in view-only mode so a locked map can't be edited via Logix.
	const logixReadonly = ref(false);

	// Delete-with-script confirmation state
	const showDeleteScriptConfirm = ref(false);

	const deleteScriptConfirmData = ref({ elements: [], scriptNames: [], usageMap: {} });

	// Shared DocType/Module options (used by notification dialog composable)
	const doctypeOptions = ref([]);

	const moduleOptions = ref([]);

	const doctypeSearch = ref("");

	const moduleSearch = ref("");

	// Markdown Editor state
	const showMarkdownEditorDialog = ref(false);

	const markdownEditorContent = ref("");

	// Call Activity Search state
	const showCallActivitySearchDialog = ref(false);

	// Zoom handlers
	const currentZoomLevel = ref(100);

	// --- Notify Assignee Editor (User Task) ---
	const showNotifyAssigneeDialog = ref(false);

	const notifyAssigneeValues = ref({});

	const notifyAssigneeDoctype = ref("");

	const notifyAssigneeTaskName = ref("");

	const notifyAssigneeTaskActions = ref([]);

	// --- Email Notification Editor (Service Task) ---
	const showEmailNotificationDialog = ref(false);

	const emailNotificationValues = ref({});

	const pc = {
		props,
		router,
		route,
		isMobile,
		showCompactDiagramMenu,
		otherEditors,
		editorRef,
		processName,
		diagrams,
		openTabs,
		activeDiagramName,
		saving,
		importing,
		editorReady,
		hasUnsavedChanges,
		loading,
		showFileMenu,
		showStatusPopup,
		showMobileMoreMenu,
		deploying,
		disabling,
		showDisableDialog,
		disableRunningCount,
		showNonExecutableDialog,
		nonExecutableActivating,
		nonExecutableBusy,
		showActionsMenu,
		connectToProduction,
		instanceType,
		showReviewDialog,
		reviewKind,
		prBaseBranch,
		reviewStage,
		reviewChanges,
		reviewResult,
		reassignMode,
		pendingReassignments,
		touchedReassignModels,
		showDmnEditorDialog,
		dmnEditorRef,
		dmnEditorTitle,
		dmnEditorXml,
		dmnEditorKey,
		isExecutable,
		showReadinessDialog,
		readinessChecklist,
		readinessMode,
		readinessLoading,
		showExportConfigDialog,
		exportConfigCounts,
		showConfigImportResults,
		configImportResults,
		configImporting,
		importConfigFileInput,
		versionDiffRef,
		compareDialogRef,
		namedVersionTabs,
		activeVersionName,
		isEditable,
		editabilityInfo,
		importFileInput,
		saveState,
		notification,
		showUnsavedNavigationWarning,
		diagramDataCache,
		showScriptEditorDialog,
		scriptEditorTitle,
		scriptDialogMode,
		serverScripts,
		serverScriptSearch,
		selectedServerScript,
		loadingScripts,
		creatingScript,
		showDoctypeDropdown,
		showModuleDropdown,
		previewScriptContent,
		loadingPreview,
		linkedScriptName,
		editScriptContent,
		editScriptMeta,
		loadingEditScript,
		savingEditScript,
		newScript,
		showLogixCanvas,
		logixElement,
		logixScriptType,
		logixCurrentScript,
		logixEventBus,
		logixProcessContext,
		logixReadonly,
		showDeleteScriptConfirm,
		deleteScriptConfirmData,
		doctypeOptions,
		moduleOptions,
		doctypeSearch,
		moduleSearch,
		showMarkdownEditorDialog,
		markdownEditorContent,
		showCallActivitySearchDialog,
		currentZoomLevel,
		showNotifyAssigneeDialog,
		notifyAssigneeValues,
		notifyAssigneeDoctype,
		notifyAssigneeTaskName,
		notifyAssigneeTaskActions,
		showEmailNotificationDialog,
		emailNotificationValues,
		heartbeatInterval: null,
		reassignSaveTimer: null,
		activeDmnElement: null,
		activeDmnEventBus: null,
		activeDmnDecisionId: null,
		lastReadinessXml: "",
		pendingExportXml: "",
		pendingExportTitle: "",
		saveTimeout: null,
		hasPendingSave: false,
		pendingNavigationNext: null,
		activeScriptEvent: null,
		pendingDeleteElements: null,
		pendingDeleteModeling: null,
		activeMarkdownEvent: null,
		callActivitySearchEvent: null,
		notifyAssigneeEvent: null,
		emailNotificationEvent: null,
	};

	// Notification Dialog (Send Task)
	pc.notifDialog = useNotificationDialog(doctypeOptions, moduleOptions, (...args) =>
		pc.showNotification(...args),
	);
	provide("notifDialog", pc.notifDialog);
	provide("notification", notification);

	return pc;
}
