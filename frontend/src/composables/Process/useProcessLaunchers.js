import { computed, watch } from "vue";
import { frappeRequest } from "frappe-ui";

export function useProcessLaunchers(pc) {
	const {
		editorRef,
		showMarkdownEditorDialog,
		markdownEditorContent,
		showCallActivitySearchDialog,
		showNotifyAssigneeDialog,
		notifyAssigneeValues,
		notifyAssigneeDoctype,
		notifyAssigneeTaskName,
		notifyAssigneeTaskActions,
		showEmailNotificationDialog,
		emailNotificationValues,
	} = pc;

	// Notification editor launch handler delegates to composable
	function onLaunchNotificationEditor(event) {
		pc.notifDialog.openDialog(event);
	}

	watch(showNotifyAssigneeDialog, (isOpen) => {
		if (!isOpen) {
			pc.notifyAssigneeEvent = null;
			notifyAssigneeValues.value = {};
		}
	});

	function onLaunchNotifyAssigneeEditor(event) {
		pc.notifyAssigneeEvent = event;
		notifyAssigneeValues.value = event.values;
		notifyAssigneeDoctype.value = event.doctype;
		notifyAssigneeTaskName.value = event.taskName;
		notifyAssigneeTaskActions.value = event.taskActions;
		showNotifyAssigneeDialog.value = true;
	}

	function onSaveNotifyAssigneeBody(values) {
		// Auto-save fires this repeatedly - keep notifyAssigneeEvent alive until the
		// dialog closes (the showNotifyAssigneeDialog watcher clears it).
		if (pc.notifyAssigneeEvent && pc.notifyAssigneeEvent.eventBus) {
			pc.notifyAssigneeEvent.eventBus.fire("spiff.userTask.notifyAssignee.update", {
				element: pc.notifyAssigneeEvent.element,
				values,
			});
		}
	}

	function onLaunchEmailNotificationEditor(event) {
		pc.emailNotificationEvent = event;
		emailNotificationValues.value = event.values;
		showEmailNotificationDialog.value = true;
	}

	function onSaveEmailNotification({ values, changed }) {
		pc.emailNotificationEvent?.eventBus.fire("spiff.serviceTask.emailNotification.update", {
			element: pc.emailNotificationEvent.element,
			values,
			changed,
		});
		showEmailNotificationDialog.value = false;
	}

	function onLaunchMarkdownEditor(event) {
		pc.activeMarkdownEvent = event;
		markdownEditorContent.value = event.value || "";
		showMarkdownEditorDialog.value = true;
	}

	function saveMarkdown() {
		if (pc.activeMarkdownEvent && pc.activeMarkdownEvent.eventBus) {
			pc.activeMarkdownEvent.eventBus.fire("spiff.markdown.update", {
				element: pc.activeMarkdownEvent.element,
				value: markdownEditorContent.value,
			});
		}
		showMarkdownEditorDialog.value = false;
		pc.activeMarkdownEvent = null;
	}

	async function onLaunchCallActivityEditor(event) {
		const calledProcess = event.element?.businessObject?.get("spiffworkflow:calledProcess");
		if (!event.processId && calledProcess) {
			window.open(
				`/processa/process/${encodeURIComponent(calledProcess)}`,
				"_blank",
				"noopener,noreferrer",
			);
			return;
		}
		if (!event.processId) {
			pc.showNotification(
				"Call Activity",
				"No process linked. Use the Search button to select a process first.",
				"orange",
			);
			return;
		}

		try {
			// Use the dedicated resolve endpoint - returns one record without
			// fetching the entire model list client-side.
			const response = await frappeRequest({
				url: "/api/method/processa.api.process_maps.resolve_process_model_by_id",
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
				pc.showNotification(
					"Call Activity",
					`Linked process "${event.processId}" not found in this system.`,
					"orange",
				);
			}
		} catch {
			pc.showNotification("Call Activity", "Failed to look up linked process.", "red");
		}
	}

	function onLaunchCallActivitySearch(event) {
		pc.callActivitySearchEvent = event;
		showCallActivitySearchDialog.value = true;
	}

	function onCallActivitySelected({ process, processId }) {
		const event = pc.callActivitySearchEvent;
		if (!event) return;

		// Primary: drive the update directly via the modeler's command stack.
		// Reliable regardless of SpiffWorkflow's async once-listener state.
		if (editorRef.value && typeof editorRef.value.updateCalledElement === "function") {
			editorRef.value.updateCalledElement(event.element, processId, process);
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
		pc.callActivitySearchEvent = null;
	}

	function onCancelCallActivitySearch() {
		// Mirror the select path: close dialog AND clear the stored event reference
		// so we don't retain stale BPMN element/eventBus objects.
		showCallActivitySearchDialog.value = false;
		pc.callActivitySearchEvent = null;
	}

	function toggleComments() {
		if (editorRef.value?.toggleTimeline) {
			editorRef.value.toggleTimeline();
		}
	}

	const totalCommentCount = computed(() => {
		return editorRef.value?.comments?.length || 0;
	});

	Object.assign(pc, {
		onLaunchNotificationEditor,
		onLaunchNotifyAssigneeEditor,
		onSaveNotifyAssigneeBody,
		onLaunchEmailNotificationEditor,
		onSaveEmailNotification,
		onLaunchMarkdownEditor,
		saveMarkdown,
		onLaunchCallActivityEditor,
		onLaunchCallActivitySearch,
		onCallActivitySelected,
		onCancelCallActivitySearch,
		toggleComments,
		totalCommentCount,
	});
}
