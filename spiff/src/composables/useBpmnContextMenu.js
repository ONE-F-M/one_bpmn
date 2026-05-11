import { ref, computed, onBeforeUnmount } from "vue";

/**
 * Composable that manages a right-click context menu on BPMN elements.
 *
 * Responsibilities:
 *   – Listens for bpmn-js `element.contextmenu` events
 *   – Positions the menu within the viewport (clamping to edges)
 *   – Respects readonly mode (hides "Add Comment", keeps "View Comments")
 *   – Dismisses on Escape / click-outside
 *   – Provides callbacks that delegate to the parent's comment helpers
 *
 * @param {Object} options
 * @param {import('vue').Ref<boolean>} options.readonly  - Whether the editor is in read-only mode
 * @param {import('vue').Ref<Array>}   options.comments  - Reactive list of all Processa Comments for this model
 * @param {Function} options.selectCommentElement        - Opens the "Add Comment" dialog for an element
 * @param {Function} options.openViewCommentsDialog      - Opens the "View Comments" dialog for an element
 */
export function useBpmnContextMenu({
	readonly,
	comments,
	selectCommentElement,
	openViewCommentsDialog,
}) {
	// ── Reactive state ───────────────────────────────────────────────────
	const showContextMenu = ref(false);
	const contextMenuPosition = ref({ x: 0, y: 0 });
	const contextMenuElement = ref(null);

	const contextMenuElementCommentCount = computed(() => {
		if (!contextMenuElement.value) return 0;
		const elementId = contextMenuElement.value.id || "process";
		return comments.value.filter((c) => c.element_id === elementId).length;
	});

	// Whether the "Add Comment" action should be shown.
	// Only allowed on real shapes — not on the root process element.
	const canAddComment = computed(() => {
		if (readonly.value) return false;
		const el = contextMenuElement.value;
		if (!el || !el.parent) return false; // root element has no parent
		return true;
	});

	// ── Viewport-clamped positioning ─────────────────────────────────────
	// Estimated dimensions for the context menu (matches the CSS min-w-[180px])
	const MENU_WIDTH = 200;
	const MENU_ITEM_HEIGHT = 36; // ~py-2 + text
	const MENU_PADDING = 8; // py-1 top + bottom

	function clampToViewport(x, y) {
		const itemCount = (canAddComment.value ? 1 : 0) + (contextMenuElementCommentCount.value > 0 ? 1 : 0);
		const estimatedHeight = MENU_PADDING + itemCount * MENU_ITEM_HEIGHT;

		const maxX = window.innerWidth - MENU_WIDTH - 4; // 4px safety margin
		const maxY = window.innerHeight - estimatedHeight - 4;

		return {
			x: Math.max(4, Math.min(x, maxX)),
			y: Math.max(4, Math.min(y, maxY)),
		};
	}

	// ── Handlers ─────────────────────────────────────────────────────────
	function openContextMenu(element, originalEvent) {
		if (!originalEvent) return;

		// Skip the root/process element — comments are only allowed on shapes
		const isRootElement = !element?.parent;
		const elementId = element?.id || "process";
		const hasComments = comments.value.some((c) => c.element_id === elementId);

		// Nothing to show if: (a) it's the root element and there are no comments,
		// or (b) readonly mode and no comments on this element.
		if (isRootElement && !hasComments) return;
		if (readonly.value && !hasComments) return;

		contextMenuElement.value = element;
		contextMenuPosition.value = clampToViewport(
			originalEvent.clientX,
			originalEvent.clientY
		);
		showContextMenu.value = true;
	}

	function addCommentFromContextMenu() {
		showContextMenu.value = false;
		if (readonly.value) return; // Guard — should never fire, but be safe
		if (contextMenuElement.value) {
			selectCommentElement(contextMenuElement.value);
		}
	}

	function viewCommentsFromContextMenu() {
		showContextMenu.value = false;
		if (!contextMenuElement.value) return;
		const elementId = contextMenuElement.value.id || "process";
		openViewCommentsDialog(elementId);
	}

	function handleContextMenuKeydown(e) {
		if (e.key === "Escape" && showContextMenu.value) {
			showContextMenu.value = false;
		}
	}

	// ── EventBus registration ────────────────────────────────────────────
	/**
	 * Call this once from inside the modeler's `onReady` callback,
	 * passing the bpmn-js eventBus instance.
	 */
	function registerEventListeners(eventBus) {
		// Context menu for comments is disabled in favor of the unified timeline
	}

	function handleDocumentClick(e) {
		if (!showContextMenu.value) return;
		// If the click is inside the context menu itself, ignore
		const menu = document.querySelector("[data-context-menu]");
		if (menu && menu.contains(e.target)) return;
		showContextMenu.value = false;
	}

	// ── Cleanup ──────────────────────────────────────────────────────────
	onBeforeUnmount(() => {
		document.removeEventListener("keydown", handleContextMenuKeydown);
		document.removeEventListener("mousedown", handleDocumentClick, true);
	});

	return {
		// State (template bindings)
		showContextMenu,
		contextMenuPosition,
		contextMenuElementCommentCount,
		canAddComment,

		// Actions (template bindings)
		addCommentFromContextMenu,
		viewCommentsFromContextMenu,

		// Lifecycle (called from BpmnEditor setup)
		registerEventListeners,
	};
}
