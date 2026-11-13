import { frappeRequest } from "frappe-ui";

export function useProcessTabs(pc) {
	const {
		props,
		router,
		editorRef,
		diagrams,
		openTabs,
		activeDiagramName,
		saving,
		hasUnsavedChanges,
		versionDiffRef,
		compareDialogRef,
		namedVersionTabs,
		activeVersionName,
		isEditable,
		saveState,
		diagramDataCache,
	} = pc;

	async function handleDeleteTab(tab) {
		if (!isEditable.value) return;
		if (
			!confirm(
				`Are you sure you want to delete "${tab.model_name}"? This action cannot be undone.`,
			)
		)
			return;

		// Optimistic: remove from UI immediately
		const tabIndex = openTabs.value.findIndex((t) => t.name === tab.name);
		const diagramIndex = diagrams.value.findIndex((d) => d.name === tab.name);
		const removedTab = tabIndex > -1 ? openTabs.value.splice(tabIndex, 1)[0] : null;
		const removedDiagram =
			diagramIndex > -1 ? diagrams.value.splice(diagramIndex, 1)[0] : null;
		delete diagramDataCache.value[tab.name];

		// Switch active tab if the deleted tab was active
		const wasActive = activeDiagramName.value === tab.name;
		if (wasActive) {
			// Clear unsaved state so selectDiagram doesn't try to save the deleted diagram
			clearTimeout(pc.saveTimeout);
			pc.hasPendingSave = false;
			hasUnsavedChanges.value = false;
			saveState.value = "idle";

			const fallback = pc.pickDefaultDiagram();
			if (fallback) {
				pc.selectDiagram(fallback);
			} else {
				activeDiagramName.value = null;
				openTabs.value = [];
				router.replace({ name: "ProcessEditor", params: { process: props.process } });
			}
		}

		// Show notification immediately (optimistic)
		pc.showNotification("Deleted", `Diagram "${tab.model_name}" has been deleted`, "green");

		// Server call (no loadProcess round-trip)
		try {
			await frappeRequest({
				url: "/api/method/processa.api.process_maps.delete_diagram",
				params: { name: tab.name },
			});
		} catch (error) {
			// Rollback on failure
			console.error("Deletion failed:", error);
			if (removedDiagram) diagrams.value.splice(diagramIndex, 0, removedDiagram);
			if (wasActive) {
				// Restore the deleted map as the (single) visible tab
				pc.selectDiagram(tab.name);
			} else if (removedTab) {
				openTabs.value.splice(tabIndex, 0, removedTab);
			}
			pc.showNotification(
				"Error",
				"Failed to delete diagram: " + (error.message || error),
				"red",
			);
		}
	}

	async function closeTab(name) {
		// If closing the active tab with pending changes, save silently first
		if (activeDiagramName.value === name && pc.isUnsavedOrInFlight()) {
			clearTimeout(pc.saveTimeout);
			pc.hasPendingSave = false;
			await pc.saveCurrentDiagram();
		}

		const index = openTabs.value.findIndex((t) => t.name === name);
		if (index > -1) {
			openTabs.value.splice(index, 1);

			// If closing active tab, switch to another
			if (activeDiagramName.value === name) {
				if (openTabs.value.length > 0) {
					const newIndex = Math.min(index, openTabs.value.length - 1);
					pc.selectDiagram(openTabs.value[newIndex].name);
				} else {
					activeDiagramName.value = null;
				}
			}
		}
	}

	/**
	 * Apply field updates to matching entries in both diagrams and openTabs.
	 * Keeps the update/revert logic in one place (Review #2).
	 */

	function applyTabDiagramFields(matchName, fields) {
		const diagramEntry = diagrams.value.find((d) => d.name === matchName);
		const tabEntry = openTabs.value.find((t) => t.name === matchName);
		if (diagramEntry) Object.assign(diagramEntry, fields);
		if (tabEntry) Object.assign(tabEntry, fields);
	}

	async function renameProcessModel({ tabName, oldModelName, newModelName }) {
		if (!isEditable.value) return; // Guard: process is locked
		// Cancel the debounce timer so autosave can't fire with a stale model_name.
		clearTimeout(pc.saveTimeout);
		pc.hasPendingSave = false;

		// If there are unsaved diagram changes, flush them under the OLD name first.
		if (hasUnsavedChanges.value && activeDiagramName.value === tabName && editorRef.value) {
			await pc.saveCurrentDiagram();
		}

		// Optimistic: show new name + notification immediately
		applyTabDiagramFields(tabName, { model_name: newModelName, title: newModelName });
		pc.showNotification("Renamed", `Diagram renamed to "${newModelName}"`, "green");

		try {
			const response = await frappeRequest({
				url: "/api/method/processa.api.process_maps.rename_process_model",
				params: {
					name: tabName,
					new_title: newModelName,
				},
			});

			const result = response.message || response;
			const newName = result.name;
			const actualModelName = result.model_name;

			// Transfer cached XML to new key (name changes because autoname = field:title)
			if (diagramDataCache.value[tabName]) {
				diagramDataCache.value[newName] = diagramDataCache.value[tabName];
				if (newName !== tabName) {
					delete diagramDataCache.value[tabName];
				}
			}

			// Confirm server-side name + display fields
			applyTabDiagramFields(tabName, {
				name: newName,
				model_name: actualModelName,
				title: actualModelName,
			});

			// Update active diagram ref and URL if the renamed tab is active
			if (activeDiagramName.value === tabName) {
				activeDiagramName.value = newName;
				router.replace({
					name: "DiagramEditor",
					params: { process: props.process, diagram: newName },
				});
			}
		} catch (error) {
			// Rollback on failure
			console.error("Failed to rename process model:", error);
			applyTabDiagramFields(tabName, { model_name: oldModelName, title: oldModelName });
			pc.showNotification(
				"Rename Failed",
				error.message || error._server_messages || "An error occurred while renaming.",
				"red",
			);
		}
	}

	// Deployed-version compare (legacy picker, kept available).
	function openVersionPicker() {
		if (!versionDiffRef.value) return;

		versionDiffRef.value.open(getCurrentDiagramXml);
	}

	// Shared getter for the current canvas XML.
	async function getCurrentDiagramXml() {
		if (editorRef.value) {
			return await editorRef.value.getXML();
		}
		return diagramDataCache.value[activeDiagramName.value] || null;
	}

	// Open the full-page version history (Google-Docs-style), not a sidebar.
	function toggleVersionHistory() {
		if (!activeDiagramName.value) return;
		router.push({
			name: "VersionHistory",
			params: { process: props.process, diagram: activeDiagramName.value },
		});
	}

	// Open the compare-versions dialog (named version vs latest).
	function openCompareDialog() {
		if (!activeDiagramName.value || !compareDialogRef.value) return;
		compareDialogRef.value.open(getCurrentDiagramXml);
	}

	// Load the active map's named versions for display as read-only chips.
	async function loadNamedVersionTabs() {
		namedVersionTabs.value = [];
		if (!activeDiagramName.value) return;
		try {
			const res = await frappeRequest({
				url: "/api/method/processa.api.versions.get_edit_history",
				params: { model_name: activeDiagramName.value },
			});
			const groups = res.message || res || [];
			namedVersionTabs.value = groups
				.filter((g) => g.is_named)
				.map((g) => ({
					name: g.head,
					version_name: g.version_name,
					timestamp: g.timestamp,
				}));
		} catch (error) {
			console.error("Failed to load named versions:", error);
		}
	}

	// Selecting a map tab leaves any version-preview and returns to the live map.
	async function onSelectTab(name) {
		const wasViewingVersion = !!activeVersionName.value;
		activeVersionName.value = null;
		if (name === activeDiagramName.value) {
			// Reload the live diagram to replace the read-only snapshot preview.
			if (wasViewingVersion) await pc.loadDiagramContent(activeDiagramName.value);
			return;
		}
		pc.selectDiagram(name);
	}

	// View a named version read-only in the editor canvas.
	async function selectVersion(versionName) {
		if (activeVersionName.value === versionName) return;

		// Persist any unsaved edits to the live map before switching to a preview.
		if (
			!activeVersionName.value &&
			hasUnsavedChanges.value &&
			activeDiagramName.value &&
			editorRef.value
		) {
			clearTimeout(pc.saveTimeout);
			saving.value = true;
			await pc.saveCurrentDiagram();
		}

		activeVersionName.value = versionName;
		try {
			const res = await frappeRequest({
				url: "/api/method/processa.api.versions.get_snapshot_xml",
				params: { version_name: versionName },
			});
			const snap = res.message || res;
			if (snap?.xml_content && editorRef.value) {
				await editorRef.value.loadXML(snap.xml_content);
			}
		} catch (error) {
			console.error("Failed to load version:", error);
			pc.showNotification("Error", "Failed to load this version.", "red");
			activeVersionName.value = null;
		}
	}

	Object.assign(pc, {
		handleDeleteTab,
		closeTab,
		applyTabDiagramFields,
		renameProcessModel,
		openVersionPicker,
		getCurrentDiagramXml,
		toggleVersionHistory,
		openCompareDialog,
		loadNamedVersionTabs,
		onSelectTab,
		selectVersion,
	});
}
