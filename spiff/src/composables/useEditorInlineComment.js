import { nextTick, onUnmounted } from "vue";
import { frappeRequest } from "frappe-ui";

export function useEditorInlineComment(ed) {
	const {
		props,
		timelineText,
		activeCommentElement,
		commentFormData,
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
	} = ed;

	function openInlineComment(element) {
		if (props.readonly) return;

		activeCommentElement.value = element;
		inlineCommentElement.value = element;
		inlineCommentFormData.value = {
			text: "",
			assigned_to: "",
			is_task: false,
		};
		inlineMentionedUsers.value = [];
		userSearchQuery.value = "";
		showInlineCommentPopover.value = true;

		const overlays = ed.modeler.get("overlays");
		// Remove any existing inline popover
		overlays.remove({ type: "inline-comment" });

		nextTick(() => {
			// Create a stable DOM target for the Teleport
			const target = document.createElement("div");
			target.className = "inline-comment-overlay-wrapper";

			overlays.add(element.id, "inline-comment", {
				position: {
					bottom: -20,
					right: -20,
				},
				html: target,
				scale: false,
			});

			inlineCommentOverlayTarget.value = target;

			// Focus textarea
			setTimeout(() => {
				if (inlineCommentPopoverEl.value) {
					const textarea = inlineCommentPopoverEl.value.querySelector("textarea");
					if (textarea) textarea.focus();
				}
			}, 50);
		});
	}

	function closeInlineComment(force = false) {
		if (!force && inlineCommentFormData.value.text) return;

		showInlineCommentPopover.value = false;
		inlineCommentElement.value = null;
		inlineCommentOverlayTarget.value = null; // Unmounts the Teleport content

		const overlays = ed.modeler.get("overlays");
		overlays.remove({ type: "inline-comment" });
	}

	async function submitInlineComment() {
		if (!inlineCommentFormData.value.text || !props.modelName || !inlineCommentElement.value)
			return;

		try {
			await frappeRequest({
				url: "/api/method/one_bpmn.api.canvas_comments.post_canvas_comment",
				params: {
					model_name: props.modelName,
					element_id: inlineCommentElement.value.id,
					comment: inlineCommentFormData.value.text,
					assigned_to: inlineCommentFormData.value.assigned_to,
					is_task: inlineCommentFormData.value.is_task ? 1 : 0,
				},
			});

			closeInlineComment(true);
			// Small delay to ensure DB commit before re-fetching
			setTimeout(() => ed.fetchComments(), 300);

			// To fix unresponsiveness, re-select the element after a short delay
			// which forces the context pad to refresh and ensures interaction is restored.
			setTimeout(() => {
				if (inlineCommentElement.value) {
					const selection = ed.modeler.get("selection");
					selection.select(inlineCommentElement.value);
				}
			}, 100);
		} catch (err) {
			console.error("Failed to post inline comment:", err);
		}
	}

	function handleInlineCommentInput(e) {
		// Reusing mention logic for inline popover
		if (!e || !e.target || typeof e.target.selectionStart !== "number") return;

		const text = inlineCommentFormData.value.text || "";

		// Sync mentioned users (checking if @user.label is still in text)
		if (!text) {
			inlineMentionedUsers.value = [];
			inlineCommentFormData.value.assigned_to = "";
			inlineCommentFormData.value.is_task = false;
		} else {
			const currentUsers = inlineMentionedUsers.value.filter((u) =>
				text.includes("@" + u.label),
			);
			if (currentUsers.length !== inlineMentionedUsers.value.length) {
				inlineMentionedUsers.value = currentUsers;
				if (
					!currentUsers.some((u) => u.value === inlineCommentFormData.value.assigned_to)
				) {
					inlineCommentFormData.value.assigned_to =
						currentUsers.length > 0 ? currentUsers[0].value : "";
					if (currentUsers.length === 0) {
						inlineCommentFormData.value.is_task = false;
					}
				}
			}
		}

		const cursorPosition = e.target.selectionStart;
		const textBeforeCursor = text.substring(0, cursorPosition);
		const match = textBeforeCursor.match(/@([^\s]{0,30})$/);

		if (match) {
			showMentionDropdown.value = true;
			mentionSearchQuery.value = match[1];
			mentionStartIndex.value = cursorPosition - match[1].length - 1;
			activeMentionContext.value = "inline";
		} else {
			showMentionDropdown.value = false;
		}

		// Auto-resize textarea
		nextTick(() => ed.autoResizeTextarea(e.target));
	}

	function selectMention(user) {
		const isTimeline = activeMentionContext.value === "timeline";
		const isInline = activeMentionContext.value === "inline";
		const targetData = isTimeline
			? timelineText
			: isInline
				? inlineCommentFormData
				: commentFormData;

		const text = isTimeline ? targetData.value : targetData.value.text;
		const before = text.substring(0, mentionStartIndex.value);
		const after = text.substring(
			mentionStartIndex.value + mentionSearchQuery.value.length + 1,
		);
		const newText = before + "@" + user.label + " " + after;

		if (isTimeline) {
			timelineText.value = newText;
			if (!timelineMentionedUsers.value.some((u) => u.value === user.value)) {
				timelineMentionedUsers.value.push(user);
			}
			timelineAssignedTo.value = user.value;
			// Auto-enable task mode if we mention someone in the timeline
			timelineIsTask.value = true;
		} else if (isInline) {
			inlineCommentFormData.value.text = newText;
			if (!inlineMentionedUsers.value.some((u) => u.value === user.value)) {
				inlineMentionedUsers.value.push(user);
			}
			inlineCommentFormData.value.assigned_to = user.value;
			inlineCommentFormData.value.is_task = true;
		} else {
			commentFormData.value.text = newText;
		}

		showMentionDropdown.value = false;

		// Refocus textarea
		nextTick(() => {
			const selector = isTimeline
				? ".timeline-textarea"
				: isInline
					? ".inline-comment-textarea"
					: ".main-comment-textarea";
			const textarea = document.querySelector(selector);
			if (textarea) textarea.focus();
		});
	}

	ed.onReady(() => {
		// Global click listener for closing inline popover/dropdowns
		const handleGlobalClick = (e) => {
			if (!showInlineCommentPopover.value) return;

			const target = e.target;
			const popover = inlineCommentPopoverEl.value;
			const isInsidePopover = popover?.contains(target);

			// Close user dropdown if click is outside the assignment input area
			const isInsideUserSearch = target.closest(".user-search-container");
			if (!isInsideUserSearch) {
				showUserDropdown.value = false;
			}

			// Close mention dropdown if click is outside the textarea area
			const isInsideTextArea = target.closest("textarea");
			const isInsideMentions = target.closest(".mentions-container");
			if (!isInsideTextArea && !isInsideMentions) {
				showMentionDropdown.value = false;
			}

			// Close popover if clicked outside and empty
			if (!isInsidePopover && !inlineCommentFormData.value.text) {
				closeInlineComment(true);
			}
		};
		document.addEventListener("mousedown", handleGlobalClick);

		onUnmounted(() => {
			document.removeEventListener("mousedown", handleGlobalClick);
		});
	});

	Object.assign(ed, {
		openInlineComment,
		closeInlineComment,
		submitInlineComment,
		handleInlineCommentInput,
		selectMention,
	});
}
