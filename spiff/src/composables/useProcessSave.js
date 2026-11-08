import { computed } from "vue";
import { onBeforeRouteLeave } from "vue-router";
import { frappeRequest } from "frappe-ui";
import { serverMessage } from "@/utils/serverMessage";

export function useProcessSave(pc) {
	const {
		props,
		editorRef,
		diagrams,
		activeDiagramName,
		saving,
		editorReady,
		hasUnsavedChanges,
		isExecutable,
		activeVersionName,
		saveState,
		notification,
		showUnsavedNavigationWarning,
		diagramDataCache,
	} = pc;

	// True while the analyst is actively typing in a Processa shape-property field
	// (any input/select/textarea/contenteditable inside the properties panel). We use
	// this to defer auto-save so a value being entered isn't saved half-finished and
	// the panel refresh/save cycle doesn't interrupt the user mid-edit.
	function isEditingShapeProperties() {
		const el = document.activeElement;
		if (!el || !el.closest) return false;
		if (!el.closest(".properties-panel-container")) return false;
		const tag = el.tagName;
		return (
			tag === "INPUT" ||
			tag === "TEXTAREA" ||
			tag === "SELECT" ||
			el.isContentEditable === true
		);
	}

	// Returns true when there are edits that haven't reached the server yet
	// (the debounce timer is ticking, a save is in-flight, or a save failed).
	function isUnsavedOrInFlight() {
		return pc.hasPendingSave || hasUnsavedChanges.value || saving.value;
	}

	// Derive status from the currently selected diagram tab
	const processStatus = computed(() => {
		if (!activeDiagramName.value) return "";
		const d = diagrams.value.find((d) => d.name === activeDiagramName.value);
		return d ? d.status : "";
	});

	const saveStatusText = computed(() => {
		switch (saveState.value) {
			case "unsaved":
				return "Unsaved changes";
			case "saving":
				return "Saving...";
			case "saved":
				return "Saved";
			case "error":
				return "Save Error";
			default:
				return "";
		}
	});

	const saveStatusColor = computed(() => {
		switch (saveState.value) {
			case "unsaved":
				return "text-orange-600";
			case "saving":
				return "text-blue-600";
			case "saved":
				return "text-green-600";
			case "error":
				return "text-red-600";
			default:
				return "text-transparent";
		}
	});

	const lastEditTooltip = computed(() => {
		if (!activeDiagramName.value) return "Version History";
		const d = diagrams.value.find((d) => d.name === activeDiagramName.value);
		if (!d || !d.modified) return "Version History";

		const modified = new Date(d.modified);
		const now = new Date();
		const diffMs = now - modified;
		const diffMins = Math.floor(diffMs / 60000);
		const diffHours = Math.floor(diffMs / 3600000);
		const diffDays = Math.floor(diffMs / 86400000);

		let timeStr;
		if (diffMins < 1) timeStr = "just now";
		else if (diffMins < 60) timeStr = `${diffMins} minute${diffMins > 1 ? "s" : ""} ago`;
		else if (diffHours < 24) timeStr = `${diffHours} hour${diffHours > 1 ? "s" : ""} ago`;
		else if (diffDays === 1)
			timeStr = `yesterday at ${modified.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })}`;
		else
			timeStr = `on ${modified.toLocaleDateString()} at ${modified.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })}`;

		const user = d.modified_by_name || "";
		return user ? `Last edit was made ${timeStr} by ${user}` : `Last edit was made ${timeStr}`;
	});

	// Keyboard shortcut handler
	function handleKeyDown(event) {
		// Ctrl+S or Cmd+S to save (only when editable)
		if ((event.ctrlKey || event.metaKey) && event.key === "s") {
			event.preventDefault();
			if (pc.canEditActiveDiagram.value && activeDiagramName.value && !saving.value) {
				saveCurrentDiagram();
			}
		}
		// Ctrl++ or Ctrl+= to zoom in
		if ((event.ctrlKey || event.metaKey) && (event.key === "+" || event.key === "=")) {
			event.preventDefault();
			pc.handleZoomIn();
		}
		// Ctrl+- to zoom out
		if ((event.ctrlKey || event.metaKey) && event.key === "-") {
			event.preventDefault();
			pc.handleZoomOut();
		}
		// Ctrl+0 to reset zoom
		if ((event.ctrlKey || event.metaKey) && event.key === "0") {
			event.preventDefault();
			pc.handleResetZoom();
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
			pc.pendingNavigationNext = next;
		} else {
			next();
		}
	});

	function confirmNavigation() {
		showUnsavedNavigationWarning.value = false;
		if (pc.pendingNavigationNext) {
			pc.pendingNavigationNext(); // allow the route change to proceed
			pc.pendingNavigationNext = null;
		}
	}

	function cancelNavigation() {
		showUnsavedNavigationWarning.value = false;
		if (pc.pendingNavigationNext) {
			pc.pendingNavigationNext(false); // block the route change
			pc.pendingNavigationNext = null;
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
		// Do not trigger auto-save when this map is locked
		if (!pc.canEditActiveDiagram.value) return;
		// Do not auto-save while previewing a read-only named version.
		if (activeVersionName.value) return;

		hasUnsavedChanges.value = true;
		saveState.value = "unsaved";

		clearTimeout(pc.saveTimeout);
		pc.hasPendingSave = true;
		pc.saveTimeout = setTimeout(runDebouncedSave, 1500);
	}

	// Runs when the auto-save debounce elapses. If the analyst is still entering
	// values in a shape-property field, we don't save yet - re-arm the timer so the
	// value can be finished first. hasPendingSave stays true throughout, so the
	// unsaved-changes leave guards still protect the edit. The save flushes on the
	// first tick after focus leaves the properties panel (≤1.5s later).
	function runDebouncedSave() {
		if (isEditingShapeProperties()) {
			pc.saveTimeout = setTimeout(runDebouncedSave, 1500);
			return;
		}
		pc.hasPendingSave = false;
		if (activeDiagramName.value) {
			saveCurrentDiagram();
		}
	}

	async function saveCurrentDiagram() {
		if (!activeDiagramName.value || !editorRef.value) return;
		if (!pc.canEditActiveDiagram.value) return; // Guard: this map is locked
		if (activeVersionName.value) return; // Guard: previewing a read-only version

		saving.value = true;
		saveState.value = "saving";
		try {
			const xml = await editorRef.value.getXML();
			isExecutable.value = pc.extractIsExecutable(xml);
			const diagram = diagrams.value.find((d) => d.name === activeDiagramName.value);
			const modelName = diagram?.model_name || activeDiagramName.value;
			const description = diagram?.description || "";

			await frappeRequest({
				url: "/api/method/one_bpmn.api.process_maps.save_process_model",
				params: {
					process: props.process,
					model_name: modelName,
					xml_content: xml,
					description: description,
				},
			});

			hasUnsavedChanges.value = false;
			diagramDataCache.value[activeDiagramName.value] = xml;

			saveState.value = "saved";
		} catch (error) {
			console.error("Failed to save diagram:", error);
			saveState.value = "error";
			// Surface the server-thrown message (e.g. the script-security gate's
			// summary) rather than the generic HTTP/ValidationError string. Keep it
			// on screen (stay) since a blocked save needs the author's attention.
			showNotification("Couldn't Save Process", serverMessage(error), "red", true);
		} finally {
			saving.value = false;
		}
	}

	function showNotification(title, message, theme = "green", stay = false) {
		notification.value = {
			show: true,
			title,
			message,
			theme,
		};
		if (!stay) {
			// Auto-hide after 3 seconds
			setTimeout(() => {
				if (notification.value.title === title) {
					notification.value.show = false;
				}
			}, 3000);
		}
	}

	Object.assign(pc, {
		isEditingShapeProperties,
		isUnsavedOrInFlight,
		processStatus,
		saveStatusText,
		saveStatusColor,
		lastEditTooltip,
		handleKeyDown,
		handleBeforeUnload,
		confirmNavigation,
		cancelNavigation,
		saveDiagramToCache,
		onDiagramChanged,
		runDebouncedSave,
		saveCurrentDiagram,
		showNotification,
	});
}
