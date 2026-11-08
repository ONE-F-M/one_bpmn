import { computed, nextTick, watch } from "vue";
import { frappeRequest } from "frappe-ui";
import { useBpmnContextMenu } from "@/composables/useBpmnContextMenu";

export function useEditorComments(ed) {
	const {
		props,
		comments,
		showTimeline,
		timelineFilterMode,
		timelineTaskFilter,
		showCommentDialog,
		showViewCommentsDialog,
		activeCommentElement,
		selectedElementComments,
		isCommentMode,
		commentFormData,
		users,
		userSearchQuery,
		showUserDropdown,
		showMentionDropdown,
		activeMentionContext,
		mentionSearchQuery,
		mentionStartIndex,
		modelerInstance,
		internalProcessName,
	} = ed;

	function toggleTimeline(mode = "all") {
		if (showTimeline.value && timelineFilterMode.value === mode) {
			showTimeline.value = false;
			return;
		}
		showTimeline.value = true;
		timelineFilterMode.value = mode;
		if (mode === "all" && modelerInstance.value) {
			modelerInstance.value.get("selection").select([]);
		}
	}

	function navigateToElementComments(elementId) {
		if (!elementId || elementId === "process" || !modelerInstance.value) return;

		const elementRegistry = modelerInstance.value.get("elementRegistry");
		const element = elementRegistry.get(elementId);

		if (element) {
			const selection = modelerInstance.value.get("selection");
			selection.select(element);

			// Ensure timeline shows comments for this element
			timelineFilterMode.value = "element";

			// Scroll to the element
			const canvas = modelerInstance.value.get("canvas");
			canvas.scrollToElement(element);
		}
	}

	// Right-click context menu (composable)
	const {
		showContextMenu,
		contextMenuPosition,
		contextMenuElementCommentCount,
		canAddComment,
		addCommentFromContextMenu,
		viewCommentsFromContextMenu,
		registerEventListeners: registerContextMenuListeners,
	} = useBpmnContextMenu({
		readonly: computed(() => props.readonly),
		comments,
		selectCommentElement,
		openViewCommentsDialog: (elementId) => {
			selectedElementComments.value = comments.value.filter(
				(c) => c.element_id === elementId,
			);
			showViewCommentsDialog.value = true;
		},
		toggleTimeline,
	});

	const processNameForPanel = computed(() => internalProcessName.value || props.modelName || "");

	function toggleCommentMode() {
		if (!isCommentMode.value) {
			// If an element is already selected, open the dialog immediately for it
			const selection = ed.modeler?.get("selection");
			const selected = selection?.get();
			if (selected && selected.length === 1) {
				selectCommentElement(selected[0]);
				return; // Don't enter mode if we immediately opened the dialog
			}
			isCommentMode.value = true;
		} else {
			isCommentMode.value = false;
			activeCommentElement.value = null;
			showCommentDialog.value = false;
		}
	}

	function selectCommentElement(element) {
		activeCommentElement.value = element;
		commentFormData.value = {
			text: "",
			assigned_to: "",
			is_task: false,
		};
		userSearchQuery.value = "";
		showUserDropdown.value = false;
		showCommentDialog.value = true;
		showMentionDropdown.value = false;
	}

	function handleCommentInput(e) {
		if (!e || !e.target || typeof e.target.selectionStart !== "number") return;

		const text = commentFormData.value.text || "";
		const cursorPosition = e.target.selectionStart;

		// Check text leading up to cursor for an active mention
		const textBeforeCursor = text.substring(0, cursorPosition);
		// Match `@` followed by any non-whitespace characters until the end
		const match = textBeforeCursor.match(/@([^\s]{0,30})$/);

		if (match) {
			showMentionDropdown.value = true;
			mentionSearchQuery.value = match[1];
			mentionStartIndex.value = cursorPosition - match[1].length - 1;
			activeMentionContext.value = "dialog";
		} else {
			showMentionDropdown.value = false;
		}

		// Auto-resize textarea
		nextTick(() => ed.autoResizeTextarea(e.target));
	}

	async function fetchUsers() {
		if (users.value.length > 0) return; // Already fetched
		try {
			const response = await frappeRequest({
				url: "/api/method/one_bpmn.api.utils.get_system_users",
			});
			users.value = (response.message || response || []).filter((u) => u.full_name);
		} catch (err) {
			console.error("Failed to fetch users:", err);
		}
	}

	async function fetchComments() {
		if (!props.modelName) return;
		try {
			const response = await frappeRequest({
				url: "/api/method/one_bpmn.api.canvas_comments.get_canvas_comments",
				params: { model_name: props.modelName },
			});
			comments.value = response.message || response || [];
			renderComments();
		} catch (err) {
			console.error("Failed to fetch comments:", err);
		}
	}

	function renderComments() {
		if (!ed.modeler) return;
		const overlays = ed.modeler.get("overlays");

		// Clear existing overlays of type 'processa-comment'
		overlays.remove({ type: "processa-comment" });

		// Group comments by element_id
		const grouped = comments.value.reduce((acc, c) => {
			const id = c.element_id || "process";
			if (!acc[id]) acc[id] = [];
			acc[id].push(c);
			return acc;
		}, {});

		Object.keys(grouped).forEach((elementId) => {
			const elementComments = grouped[elementId];
			const openTasks = elementComments.filter((c) => c.is_task && c.status === "Open");
			const regularComments = elementComments.filter((c) => !c.is_task);
			const hasOpenTasks = openTasks.length > 0;
			const hasRegularComments = regularComments.length > 0;

			if (!hasOpenTasks && !hasRegularComments) return;

			const html = document.createElement("div");

			if (hasOpenTasks) {
				// Show orange numeric badge for open tasks
				html.className =
					"flex items-center justify-center bg-orange-500 text-white rounded-full text-[10px] font-extrabold shadow-sm border border-white cursor-pointer hover:scale-110 transition-transform";
				html.style.width = "18px";
				html.style.height = "18px";
				html.innerText = openTasks.length;
				html.title = `${openTasks.length} open task(s)`;
			} else {
				// Show blue comment icon for regular (non-task) comments
				html.className =
					"flex items-center justify-center bg-blue-500 text-white rounded-full shadow-sm border border-white cursor-pointer hover:scale-110 transition-transform";
				html.style.width = "18px";
				html.style.height = "18px";
				// Chat-bubble SVG icon
				html.innerHTML = `<svg xmlns="http://www.w3.org/2000/svg" width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>`;
				html.title = `${regularComments.length} comment(s)`;
			}

			html.onclick = (e) => {
				e.stopPropagation();
				// Select the element
				navigateToElementComments(elementId);
				// Open timeline and filter appropriately
				showTimeline.value = true;
				timelineFilterMode.value = "element";
				timelineTaskFilter.value = hasOpenTasks;
			};

			const elementRegistry = ed.modeler.get("elementRegistry");
			const targetElement = elementRegistry.get(elementId);

			if (!targetElement) return;

			try {
				overlays.add(elementId, "processa-comment", {
					position: {
						bottom: -2,
						left: -2,
					},
					html: html,
					scale: false,
				});
			} catch (err) {
				console.error(`Failed to add overlay for element ${elementId}:`, err);
			}
		});
	}

	async function submitComment() {
		if (!commentFormData.value.text || !props.modelName) return;

		// Comments must be associated with a specific element - reject root/process
		const elementId = activeCommentElement.value?.id;
		if (!elementId || !activeCommentElement.value?.parent) {
			console.warn("Cannot add comment: no shape selected");
			return;
		}

		try {
			await frappeRequest({
				url: "/api/method/one_bpmn.api.canvas_comments.post_canvas_comment",
				params: {
					model_name: props.modelName,
					element_id: elementId,
					comment: commentFormData.value.text,
					assigned_to: commentFormData.value.assigned_to,
					is_task: commentFormData.value.is_task ? 1 : 0,
				},
			});

			showCommentDialog.value = false;
			isCommentMode.value = false;
			// Small delay to ensure DB commit before re-fetching
			setTimeout(() => fetchComments(), 300);
		} catch (err) {
			console.error("Failed to post comment:", err);
		}
	}

	async function resolveComment(comment) {
		try {
			await frappeRequest({
				url: "/api/method/one_bpmn.api.canvas_comments.update_comment_status",
				params: {
					name: comment.name,
					status: "Resolved",
				},
			});
			fetchComments();
			// Update the local list if dialog is open
			const idx = selectedElementComments.value.findIndex((c) => c.name === comment.name);
			if (idx > -1) {
				selectedElementComments.value[idx].status = "Resolved";
			}
		} catch (err) {
			console.error("Failed to resolve comment:", err);
		}
	}

	// Watch for model name changes to refetch comments
	watch(
		() => props.modelName,
		(newVal) => {
			if (newVal) {
				fetchComments();
			}
		},
	);

	ed.onReady(() => {
		const eventBus = ed.modeler.get("eventBus");
		// Fetch users for assignment
		fetchUsers();

		// Expose the current model to bpmn-js properties providers that
		// live outside Vue (Registry Tools applicability).
		window.__ONE_BPMN_CURRENT_MODEL__ = props.modelName || "";

		// Initial fetch of comments
		if (props.modelName) {
			fetchComments();
		}

		// Canvas/Element click listener for commenting
		const handleCommentClick = (element, originalEvent) => {
			if (!isCommentMode.value || !element) return;

			// Only allow comments on actual shapes - skip the root process element
			if (!element.parent) return;

			// Guard against missing originalEvent
			if (originalEvent) {
				originalEvent.preventDefault();
				originalEvent.stopPropagation();
			}

			selectCommentElement(element);
			return false;
		};

		eventBus.on("element.click", (e) => {
			return handleCommentClick(e.element, e.originalEvent);
		});

		// Canvas clicks (empty area) - intentionally ignored for commenting.
		// Comments must be associated with a shape, not the canvas.

		// Right-click context menu - delegates to composable
		registerContextMenuListeners(eventBus);

		// Listen for inline comment request from context pad
		eventBus.on("commentContextPad.addComment", ({ element }) => {
			ed.openInlineComment(element);
		});
	});

	Object.assign(ed, {
		toggleTimeline,
		navigateToElementComments,
		processNameForPanel,
		toggleCommentMode,
		selectCommentElement,
		handleCommentInput,
		fetchUsers,
		fetchComments,
		renderComments,
		submitComment,
		resolveComment,
		showContextMenu,
		contextMenuPosition,
		contextMenuElementCommentCount,
		canAddComment,
		addCommentFromContextMenu,
		viewCommentsFromContextMenu,
		registerContextMenuListeners,
	});
}
