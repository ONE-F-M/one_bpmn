import { ref, shallowRef } from "vue";

export const EDITOR_KEY = Symbol("bpmnEditor");

export function createEditorContext(props, emit) {
	// Commenting state
	const comments = ref([]);
	const timelineText = ref("");
	const showTimeline = ref(false);
	const timelineFilterMode = ref("element"); // 'element' or 'all'
	const timelineTaskFilter = ref(false);
	const timelineAssignedFilter = ref(false);
	const showCommentDialog = ref(false);
	const showViewCommentsDialog = ref(false);
	const activeCommentElement = ref(null);
	const selectedElementComments = ref([]);
	const messageDialog = ref({
		show: false,
		isEdit: false,
		name: "",
		elementId: "",
		_eventBus: null,
	});
	const aiAgentModal = ref({ show: false, element: null, mode: "agent" });
	// Docu (AI DocType builder) panel state. `_eventBus` is the properties-panel
	// eventBus that launched us - we fire "docu.doctype.update" back through it so
	// the Launch Docu button writes the applied DocType name onto the shape.
	const docuPanel = ref({ show: false, element: null, doctype: "", attr: "", _eventBus: null });
	const isCommentMode = ref(false);
	const commentFormData = ref({
		text: "",
		assigned_to: "",
		is_task: false,
	});
	const users = ref([]);
	// Inline Comment Popover state
	const showInlineCommentPopover = ref(false);
	const inlineCommentPopoverEl = ref(null);
	const inlineCommentFormData = ref({
		text: "",
		assigned_to: "",
		is_task: false,
	});
	const inlineMentionedUsers = ref([]);
	const inlineCommentElement = ref(null);
	const inlineCommentOverlayTarget = ref(null);
	const timelineAssignedTo = ref("");
	const timelineIsTask = ref(false);
	const timelineMentionedUsers = ref([]);
	const userSearchQuery = ref("");
	const showUserDropdown = ref(false);
	const showMentionDropdown = ref(false);
	const activeMentionContext = ref("");
	const mentionSearchQuery = ref("");
	const mentionStartIndex = ref(-1);
	const container = ref(null);
	const propertiesContainer = ref(null);
	const toolbarEl = ref(null);
	const canUndo = ref(false);
	const canRedo = ref(false);
	const zoomLevel = ref(100);
	// Desktop: start visible (collapsed sidebar); Mobile: start hidden (no bottom sheet on load)
	const showPropertiesPanel = ref(window.innerWidth >= 640);
	const propertiesCollapsed = ref(true);
	const isMounted = ref(false);
	const isImporting = ref(false);
	const selectedElements = shallowRef([]);
	const modelerInstance = shallowRef(null);
	const showMobileFormatPopover = ref(false);
	const showMoreTools = ref(false);
	const showProsAllyPanel = ref(false);
	const prosAllyPanel = ref(null);
	// Closing ProsAlly only hides it, so its conversation survives until the editor goes away.
	const prosAllyMounted = ref(false);
	const internalProcessName = ref("");
	const dragHandleRef = ref(null);

	const readySteps = [];
	const onReady = (step) => readySteps.push(step);

	return {
		props,
		emit,
		modeler: null,
		commandStack: null,
		readySteps,
		onReady,
		comments,
		timelineText,
		showTimeline,
		timelineFilterMode,
		timelineTaskFilter,
		timelineAssignedFilter,
		showCommentDialog,
		showViewCommentsDialog,
		activeCommentElement,
		selectedElementComments,
		messageDialog,
		aiAgentModal,
		docuPanel,
		isCommentMode,
		commentFormData,
		users,
		showInlineCommentPopover,
		inlineCommentPopoverEl,
		inlineCommentFormData,
		inlineMentionedUsers,
		inlineCommentElement,
		inlineCommentOverlayTarget,
		timelineAssignedTo,
		timelineIsTask,
		timelineMentionedUsers,
		userSearchQuery,
		showUserDropdown,
		showMentionDropdown,
		activeMentionContext,
		mentionSearchQuery,
		mentionStartIndex,
		container,
		propertiesContainer,
		toolbarEl,
		canUndo,
		canRedo,
		zoomLevel,
		showPropertiesPanel,
		propertiesCollapsed,
		isMounted,
		isImporting,
		selectedElements,
		modelerInstance,
		showMobileFormatPopover,
		showMoreTools,
		showProsAllyPanel,
		prosAllyPanel,
		prosAllyMounted,
		internalProcessName,
		dragHandleRef,
	};
}
