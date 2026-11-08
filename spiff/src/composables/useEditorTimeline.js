import { computed, nextTick, watch } from "vue";
import { frappeRequest } from "frappe-ui";

export function useEditorTimeline(ed) {
	const {
		props,
		comments,
		timelineText,
		timelineFilterMode,
		timelineTaskFilter,
		timelineAssignedFilter,
		commentFormData,
		users,
		timelineAssignedTo,
		timelineIsTask,
		timelineMentionedUsers,
		userSearchQuery,
		showMentionDropdown,
		activeMentionContext,
		mentionSearchQuery,
		mentionStartIndex,
		selectedElements,
	} = ed;

	const currentElementComments = computed(() => {
		let filtered = [];
		if (timelineFilterMode.value === "all") {
			filtered = comments.value;
		} else {
			const element = selectedElements.value[0];
			const id = element?.id || "process";
			filtered = comments.value.filter((c) => (c.element_id || "process") === id);
		}

		if (timelineTaskFilter.value) {
			filtered = filtered.filter((c) => c.is_task && c.status === "Open");
		}

		if (timelineAssignedFilter.value) {
			const currentUser =
				window.frappe?.boot?.session_user ||
				window.frappe?.session?.user ||
				window.frappe?.boot?.user?.name ||
				window.frappe?.user_name ||
				window.frappe?.user?.name;
			filtered = filtered.filter((c) => {
				// Basic guards
				if (!c.is_task || !currentUser) return false;

				// Case-insensitive status check
				const status = String(c.status || "")
					.toLowerCase()
					.trim();
				if (status !== "open") return false;

				// Normalize all available identity strings
				const assigneeId = String(c.assigned_to || "")
					.toLowerCase()
					.trim();
				const assigneeName = String(c.assigned_to_full_name || "")
					.toLowerCase()
					.trim();
				const currentUserId = String(currentUser || "")
					.toLowerCase()
					.trim();
				const currentUserFull = String(window.frappe?.boot?.user?.full_name || "")
					.toLowerCase()
					.trim();

				// 1. Direct ID match (c.akeru@one-fm.com === c.akeru@one-fm.com)
				if (assigneeId === currentUserId) return true;

				// 2. Name to Name match (Chukwuebuka Akeru === Chukwuebuka Akeru)
				if (assigneeName && currentUserFull && assigneeName === currentUserFull)
					return true;

				// 3. ID to Name cross-match (Chukwuebuka Akeru === Chukwuebuka Akeru, when one is used as ID)
				if (assigneeId && currentUserFull && assigneeId === currentUserFull) return true;

				// 4. Name to ID cross-match (Chukwuebuka Akeru === Chukwuebuka Akeru, when other is used as ID)
				if (assigneeName && currentUserId && assigneeName === currentUserId) return true;

				return false;
			});
		}

		return filtered;
	});

	const sortedTimelineComments = computed(() => {
		return [...currentElementComments.value].sort(
			(a, b) => new Date(b.creation) - new Date(a.creation),
		);
	});

	function formatCommentDate(dateStr) {
		if (!dateStr) return "";
		const d = new Date(dateStr);
		const day = String(d.getDate()).padStart(2, "0");
		const month = String(d.getMonth() + 1).padStart(2, "0");
		const year = d.getFullYear();
		const hours = String(d.getHours()).padStart(2, "0");
		const minutes = String(d.getMinutes()).padStart(2, "0");
		const seconds = String(d.getSeconds()).padStart(2, "0");
		return `${day}/${month}/${year}, ${hours}:${minutes}:${seconds}`;
	}

	async function submitTimelineComment() {
		if (!timelineText.value.trim() || !props.modelName) return;

		const element = selectedElements.value[0];
		const elementId = element?.id || "process";

		try {
			await frappeRequest({
				url: "/api/method/one_bpmn.api.canvas_comments.post_canvas_comment",
				params: {
					model_name: props.modelName,
					element_id: elementId,
					comment: timelineText.value.trim(),
					assigned_to: timelineAssignedTo.value,
					is_task: timelineIsTask.value ? 1 : 0,
				},
			});
			timelineText.value = "";
			timelineAssignedTo.value = "";
			timelineIsTask.value = false;
			timelineMentionedUsers.value = [];
			// Small delay to ensure DB commit before re-fetching
			setTimeout(() => ed.fetchComments(), 300);
		} catch (err) {
			console.error("Failed to post timeline comment:", err);
		}
	}

	function autoResizeTextarea(el) {
		if (!el) return;
		el.style.height = "auto";
		el.style.height = el.scrollHeight + "px";
	}

	function handleTimelineCommentInput(e) {
		if (!e || !e.target || typeof e.target.selectionStart !== "number") return;

		const text = timelineText.value || "";

		// Sync mentioned users
		if (!text) {
			timelineMentionedUsers.value = [];
			timelineAssignedTo.value = "";
			timelineIsTask.value = false;
		} else {
			const currentUsers = timelineMentionedUsers.value.filter((u) =>
				text.includes("@" + u.label),
			);
			if (currentUsers.length !== timelineMentionedUsers.value.length) {
				timelineMentionedUsers.value = currentUsers;
				if (!currentUsers.some((u) => u.value === timelineAssignedTo.value)) {
					timelineAssignedTo.value =
						currentUsers.length > 0 ? currentUsers[0].value : "";
					if (currentUsers.length === 0) {
						timelineIsTask.value = false;
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
			activeMentionContext.value = "timeline";
		} else {
			showMentionDropdown.value = false;
		}

		// Auto-resize textarea
		nextTick(() => autoResizeTextarea(e.target));
	}

	// Clear assigned_to when the user edits the search text away from the selected label.
	// This prevents a stale assignment if the user modifies the input after selecting someone.
	watch(userSearchQuery, (newQuery) => {
		const assignedUser = commentFormData.value.assigned_to;
		if (!assignedUser) return;

		// Find the label (full_name) of the currently assigned user
		const match = users.value.find((u) => u.name === assignedUser);
		if (match && newQuery !== match.full_name) {
			commentFormData.value.assigned_to = "";
		}
	});

	const mentionSuggestions = computed(() => {
		const q = (mentionSearchQuery.value || "").trim().toLowerCase();
		if (!q) return [];

		return users.value
			.map((u) => ({ label: u.full_name, value: u.name }))
			.filter((u) => u.label.toLowerCase().includes(q) || u.value.toLowerCase().includes(q))
			.slice(0, 10);
	});

	const filteredUsers = computed(() => {
		const q = (userSearchQuery.value || "").toLowerCase();
		const options = users.value.map((u) => ({
			label: u.full_name,
			value: u.name,
		}));
		if (!q) return options;
		return options.filter(
			(u) => u.label.toLowerCase().includes(q) || u.value.toLowerCase().includes(q),
		);
	});

	Object.assign(ed, {
		currentElementComments,
		sortedTimelineComments,
		formatCommentDate,
		submitTimelineComment,
		autoResizeTextarea,
		handleTimelineCommentInput,
		mentionSuggestions,
		filteredUsers,
	});
}
