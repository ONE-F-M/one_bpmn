import { computed, onMounted, onUnmounted, ref, watch } from "vue";
import { frappeRequest } from "frappe-ui";
import { serverMessage } from "@/utils/serverMessage";
import { useDiagramCollaboration } from "@/composables/useDiagramCollaboration";
import { useDiagramAwareness } from "@/composables/useDiagramAwareness";
import { useCurrentUser } from "@/composables/useCurrentUser";

export function useProcessDocument(pc) {
	const {
		props,
		router,
		otherEditors,
		editorRef,
		processName,
		diagrams,
		openTabs,
		activeDiagramName,
		saving,
		editorReady,
		hasUnsavedChanges,
		loading,
		showDisableDialog,
		showNonExecutableDialog,
		showDmnEditorDialog,
		isExecutable,
		showReadinessDialog,
		showExportConfigDialog,
		showConfigImportResults,
		versionDiffRef,
		compareDialogRef,
		isEditable,
		editabilityInfo,
		saveState,
		showUnsavedNavigationWarning,
		diagramDataCache,
		showScriptEditorDialog,
		showLogixCanvas,
		showDeleteScriptConfirm,
		showMarkdownEditorDialog,
		showCallActivitySearchDialog,
		showNotifyAssigneeDialog,
	} = pc;

	const activeDiagramLabel = computed(() => {
		const d = diagrams.value.find((t) => t.name === activeDiagramName.value);
		return d ? d.model_name : "Select Diagram";
	});

	const activeDiagramIsActive = computed(() => isActiveModel.value);

	const isAnyDialogOpen = computed(() => {
		return (
			showScriptEditorDialog.value ||
			showLogixCanvas.value ||
			showDeleteScriptConfirm.value ||
			showMarkdownEditorDialog.value ||
			showUnsavedNavigationWarning.value ||
			showCallActivitySearchDialog.value ||
			showReadinessDialog.value ||
			showDisableDialog.value ||
			showNonExecutableDialog.value ||
			showDmnEditorDialog.value ||
			showExportConfigDialog.value ||
			showConfigImportResults.value ||
			pc.notifDialog.showNotificationDialog.value ||
			showNotifyAssigneeDialog.value ||
			versionDiffRef.value?.isAnyDialogOpen ||
			compareDialogRef.value?.isAnyDialogOpen
		);
	});

	// True when the currently selected diagram is deployed (is_active === 1)
	const isActiveModel = computed(() => {
		if (!activeDiagramName.value) return false;
		const d = diagrams.value.find((d) => d.name === activeDiagramName.value);
		return d ? !!d.is_active : false;
	});

	function extractIsExecutable(xml) {
		try {
			const doc = new DOMParser().parseFromString(xml, "text/xml");
			const processes = doc.getElementsByTagNameNS(
				"http://www.omg.org/spec/BPMN/20100524/MODEL",
				"process",
			);
			for (let i = 0; i < processes.length; i++) {
				if (processes[i].getAttribute("isExecutable") === "true") return true;
			}
			return false;
		} catch {
			return false;
		}
	}

	// Canvas editability is per process map: the Process Implementation linked
	// to the ACTIVE map must have its 'Editable' flag checked. Site-wide gates
	// (production lock / dev bypass) override the per-map check.
	const canEditActiveDiagram = computed(() => {
		if (!isEditable.value) return false;
		if (editabilityInfo.value.override) return true;
		const d = diagrams.value.find((d) => d.name === activeDiagramName.value);
		return !!d?.implementation_editable;
	});

	// Human-readable reason shown in the lock popup.
	const lockReason = computed(() => {
		if (!isEditable.value) {
			return (
				editabilityInfo.value.reason ||
				'Process is locked. Create a Process Implementation and get it actioned to "Active" state to enable editing.'
			);
		}
		return "This process map is not linked to an editable Process Implementation, so it is read-only.";
	});

	onMounted(async () => {
		// Add keyboard shortcut listener
		window.addEventListener("keydown", pc.handleKeyDown);
		window.addEventListener("beforeunload", pc.handleBeforeUnload);

		try {
			loading.value = true;
			await loadProcess();

			// Check editability (Process Implementation status)
			await checkEditability();

			// Pick the map to show: an explicit route diagram wins, otherwise the
			// map linked to an editable Process Implementation (last modified if
			// several), otherwise the last modified map. Only ONE map is visible
			// at a time - the rest stay reachable via the bottom-bar menu.
			let initial = null;
			if (props.diagram && diagrams.value.some((d) => d.name === props.diagram)) {
				initial = props.diagram;
			} else {
				initial = pickDefaultDiagram();
			}

			if (initial) {
				activeDiagramName.value = initial;
				const d = diagrams.value.find((d) => d.name === initial);
				openTabs.value = d ? [d] : [];
			}
		} finally {
			loading.value = false;
		}
	});

	// Choose the default map: the one linked to an editable Process
	// Implementation (last modified when several are editable); if none exists,
	// the last modified map.
	function pickDefaultDiagram() {
		const list = diagrams.value;
		if (!list.length) return null;
		const byModifiedDesc = (a, b) => new Date(b.modified) - new Date(a.modified);
		const editables = list.filter((d) => d.implementation_editable);
		const pool = editables.length ? editables : list;
		return [...pool].sort(byModifiedDesc)[0].name;
	}

	async function checkEditability() {
		try {
			const response = await frappeRequest({
				url: "/api/method/one_bpmn.api.editability.check_process_editable",
				params: { process_name: props.process },
			});

			const data = response.message || response;
			isEditable.value = !!data.editable;
			editabilityInfo.value = {
				editable: !!data.editable,
				process_implementation: data.process_implementation || null,
				workflow_state: data.workflow_state || null,
				override: !!data.override,
				reason: data.reason || null,
			};
		} catch (error) {
			console.error("Failed to check process editability:", error);
			// On error, default to locked for safety
			isEditable.value = false;
			editabilityInfo.value = {
				editable: false,
				process_implementation: null,
				workflow_state: null,
				override: false,
				reason: "Unable to check editability. Process is locked for safety.",
			};
		}
	}

	onUnmounted(() => {
		// Remove listeners
		window.removeEventListener("keydown", pc.handleKeyDown);
		window.removeEventListener("beforeunload", pc.handleBeforeUnload);
		clearTimeout(pc.saveTimeout);
		leaveCollaboration();
	});

	// Shares the open diagram with the other editors of the same model.
	const collab = useDiagramCollaboration({
		hasLocalChanges: () => pc.isUnsavedOrInFlight() || pc.isEditingShapeProperties(),
		applyXml: applyRemoteDiagram,
		getLiveXml: () => editorRef.value?.getLiveXML(),
		onEditors: (editors) => {
			otherEditors.value = editors;
		},
	});

	// Shows who else has the diagram open and what they have selected.
	const { currentUser } = useCurrentUser();
	const localSelection = ref([]);
	const awareness = useDiagramAwareness({
		currentUser: () => currentUser.value,
		getSelection: () => localSelection.value,
		canEdit: () => pc.canEditActiveDiagram.value,
	});
	watch(awareness.peers, (list) => editorRef.value?.setPresence(list));

	function onSelectionChanged(ids) {
		localSelection.value = ids;
		awareness.announce();
	}

	async function applyRemoteDiagram(xml) {
		if (!editorRef.value) return;
		await editorRef.value.loadXML(xml, { keepViewbox: true });
		diagramDataCache.value[activeDiagramName.value] = xml;
		isExecutable.value = extractIsExecutable(xml);
		hasUnsavedChanges.value = false;
		saveState.value = "saved";
	}

	function markSynced(xml) {
		collab.synced(xml).catch((err) => console.error("Diagram sync failed:", err));
	}

	async function onLoadLatest() {
		try {
			await collab.loadLatest();
		} catch (error) {
			pc.showNotification("Couldn't Load Latest", serverMessage(error), "red", true);
		}
	}

	async function onKeepMine() {
		try {
			await collab.keepMine();
			await pc.saveCurrentDiagram();
		} catch (error) {
			pc.showNotification("Couldn't Save Process", serverMessage(error), "red", true);
		}
	}

	function joinCollaboration(modelName) {
		if (!modelName) return;
		collab.join(modelName).catch((err) => console.error("Collaboration join failed:", err));
		awareness.join(modelName);
	}

	function leaveCollaboration() {
		collab.leave();
		awareness.leave();
	}

	async function loadProcess() {
		try {
			const response = await frappeRequest({
				url: "/api/method/one_bpmn.api.process_maps.get_process_diagrams",
				params: { process: props.process },
			});
			const data = response.message || response;
			processName.value = data.process_name;
			diagrams.value = data.diagrams || [];
			pc.loadProductionReviewSettings();
		} catch (error) {
			console.error("Failed to load process:", error);
		}
	}

	async function selectDiagram(name) {
		if (activeDiagramName.value === name) return;

		// Save current diagram if there are unsaved changes
		if (hasUnsavedChanges.value && activeDiagramName.value && editorRef.value) {
			clearTimeout(pc.saveTimeout);
			saving.value = true;
			await pc.saveCurrentDiagram();
		}

		activeDiagramName.value = name;

		// Only one map is visible at a time - the tab bar shows just the
		// selected map; all others are reachable via the bottom-bar menu.
		const diagram = diagrams.value.find((d) => d.name === name);
		openTabs.value = diagram ? [diagram] : [];

		// Update URL (skip in compact mode - parent manages routing)
		if (!props.compact) {
			router.replace({
				name: "DiagramEditor",
				params: { process: props.process, diagram: name },
			});
		}
		// The watch(activeDiagramName) handles loading the new diagram XML.
	}

	async function onEditorReady() {
		editorReady.value = true;

		// Load the initial diagram content (fires only once on first mount)
		if (activeDiagramName.value) {
			await loadDiagramContent(activeDiagramName.value);
			await pc.loadNamedVersionTabs();
			hasUnsavedChanges.value = false;
		}

		hasUnsavedChanges.value = false;
		saveState.value = "saved";
	}

	// Watch for diagram tab switches and load new XML without remounting the editor.
	watch(activeDiagramName, async (newName) => {
		if (!newName) {
			leaveCollaboration();
			isExecutable.value = false;
			return;
		}

		joinCollaboration(newName);

		if (!editorReady.value) return;
		hasUnsavedChanges.value = false;
		saveState.value = "saved";
		await loadDiagramContent(newName);
		await pc.loadNamedVersionTabs();
		hasUnsavedChanges.value = false;
	});

	async function loadDiagramContent(name) {
		// Check cache first
		if (diagramDataCache.value[name]) {
			if (editorRef.value) {
				await editorRef.value.loadXML(diagramDataCache.value[name]);
				if (processName.value) editorRef.value.setProcessName(processName.value);
				isExecutable.value = extractIsExecutable(diagramDataCache.value[name]);
				markSynced(diagramDataCache.value[name]);
			}
			return;
		}

		try {
			const response = await frappeRequest({
				url: "/api/method/one_bpmn.api.process_maps.get_process_model",
				params: { name },
			});

			const data = response.message || response;
			if (data && data.xml_content && editorRef.value) {
				diagramDataCache.value[name] = data.xml_content;
				await editorRef.value.loadXML(data.xml_content);
				if (processName.value) editorRef.value.setProcessName(processName.value);
				isExecutable.value = extractIsExecutable(data.xml_content);
				markSynced(data.xml_content);
			}
		} catch (error) {
			console.error("Failed to load diagram:", error);
		}
	}

	function goBack() {
		router.push({ name: "Home" });
	}

	function getStatusTheme(status) {
		switch (status) {
			case "Active":
				return "green";
			case "Inactive":
				return "orange";
			default:
				return "gray";
		}
	}

	Object.assign(pc, {
		activeDiagramLabel,
		activeDiagramIsActive,
		isAnyDialogOpen,
		isActiveModel,
		extractIsExecutable,
		canEditActiveDiagram,
		lockReason,
		pickDefaultDiagram,
		checkEditability,
		collab,
		awareness,
		onSelectionChanged,
		onLoadLatest,
		onKeepMine,
		loadProcess,
		selectDiagram,
		onEditorReady,
		loadDiagramContent,
		goBack,
		getStatusTheme,
	});
}
