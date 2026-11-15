import { frappeRequest } from "frappe-ui";
import { downloadBpmn, sanitiseFilename } from "@/utils/downloadBpmn";

export function useProcessConfig(pc) {
	const {
		props,
		router,
		editorRef,
		diagrams,
		openTabs,
		activeDiagramName,
		importing,
		showReadinessDialog,
		readinessMode,
		showExportConfigDialog,
		exportConfigCounts,
		showConfigImportResults,
		configImportResults,
		configImporting,
		importConfigFileInput,
		importFileInput,
		diagramDataCache,
	} = pc;

	// Called when ConfigImportResultsDialog is done (all decisions applied)
	async function onConfigImportDone() {
		// If readiness dialog is still open, recheck automatically
		if (showReadinessDialog.value && pc.lastReadinessXml) {
			await pc.runReadinessCheck(pc.lastReadinessXml, readinessMode.value);
		}
	}

	async function exportCurrentDiagram() {
		if (!activeDiagramName.value || !editorRef.value) return;

		try {
			const xml = await editorRef.value.getXML();
			const diagram = diagrams.value.find((d) => d.name === activeDiagramName.value);
			const title = diagram?.model_name || activeDiagramName.value;

			// Check if diagram references any config records
			try {
				const resp = await frappeRequest({
					url: "/api/method/processa.api.config_export_import.export_bpmn_config",
					params: { xml_content: xml },
				});
				const data = resp.message || resp;
				const counts = data.counts || {};
				const total =
					(counts.server_scripts || 0) +
					(counts.workflow_states || 0) +
					(counts.workflow_action_masters || 0);

				if (total > 0) {
					// Has config records → show popup
					pc.pendingExportXml = xml;
					pc.pendingExportTitle = title;
					exportConfigCounts.value = counts;
					showExportConfigDialog.value = true;
					return;
				}
			} catch (e) {
				// If config check fails, just export BPMN only
				console.warn("Config export check failed, exporting BPMN only:", e);
			}

			// No config records or check failed - export BPMN directly
			const filename = downloadBpmn(xml, title);
			pc.showNotification("Exported", `Downloaded as ${filename}`, "green");
		} catch (error) {
			console.error("Failed to export diagram:", error);
			pc.showNotification("Error", "Failed to export diagram", "red");
		}
	}

	// Export BPMN only (from ExportConfigDialog)
	function doExportBpmnOnly() {
		if (pc.pendingExportXml) {
			const filename = downloadBpmn(pc.pendingExportXml, pc.pendingExportTitle);
			pc.showNotification("Exported", `Downloaded as ${filename}`, "green");
			pc.pendingExportXml = "";
			pc.pendingExportTitle = "";
		}
	}

	// Export BPMN + Config JSON (from ExportConfigDialog)
	async function doExportWithConfig(selected) {
		if (!pc.pendingExportXml) return;

		// 1. Download BPMN
		const bpmnFilename = downloadBpmn(pc.pendingExportXml, pc.pendingExportTitle);

		// 2. Fetch full config data and download as JSON
		try {
			const resp = await frappeRequest({
				url: "/api/method/processa.api.config_export_import.export_bpmn_config",
				params: { xml_content: pc.pendingExportXml },
			});
			const data = resp.message || resp;

			// Filter by user selection
			const filteredData = {
				export_metadata: data.export_metadata,
				server_scripts: selected.server_scripts ? data.server_scripts : [],
				workflow_states: selected.workflow_states ? data.workflow_states : [],
				workflow_action_masters: selected.workflow_action_masters
					? data.workflow_action_masters
					: [],
			};

			const jsonStr = JSON.stringify(filteredData, null, 2);
			const jsonFilename = sanitiseFilename(pc.pendingExportTitle) + "-config.json";
			const blob = new Blob([jsonStr], { type: "application/json" });
			const url = URL.createObjectURL(blob);
			const link = document.createElement("a");
			link.href = url;
			link.download = jsonFilename;
			document.body.appendChild(link);
			link.click();
			document.body.removeChild(link);
			URL.revokeObjectURL(url);

			pc.showNotification(
				"Exported",
				`Downloaded ${bpmnFilename} and ${jsonFilename}`,
				"green",
			);
		} catch (error) {
			console.error("Failed to export config:", error);
			pc.showNotification(
				"Export",
				`Downloaded ${bpmnFilename} but config export failed`,
				"yellow",
			);
		}

		pc.pendingExportXml = "";
		pc.pendingExportTitle = "";
	}

	function triggerImport() {
		if (importFileInput.value) {
			// Reset so the same file can be re-imported
			importFileInput.value.value = "";
			importFileInput.value.click();
		}
	}

	function triggerImportConfig() {
		if (importConfigFileInput.value) {
			importConfigFileInput.value.value = "";
			importConfigFileInput.value.click();
		}
	}

	async function handleImportConfigFile(event) {
		const file = event.target.files && event.target.files[0];
		if (!file) return;

		configImporting.value = true;
		showConfigImportResults.value = true;
		configImportResults.value = { created: [], skipped: [], needs_confirmation: [] };

		try {
			const jsonText = await new Promise((resolve, reject) => {
				const reader = new FileReader();
				reader.onload = (e) => resolve(e.target.result);
				reader.onerror = () => reject(new Error("Failed to read file"));
				reader.readAsText(file);
			});

			const resp = await frappeRequest({
				url: "/api/method/processa.api.config_export_import.import_bpmn_config",
				method: "POST",
				params: { config_json: jsonText },
			});

			configImportResults.value = resp.message || resp;
		} catch (error) {
			console.error("Config import failed:", error);
			showConfigImportResults.value = false;
			pc.showNotification(
				"Import Failed",
				error.message || "An unexpected error occurred while importing config.",
				"red",
			);
		} finally {
			configImporting.value = false;
		}
	}

	async function handleImportFile(event) {
		const file = event.target.files && event.target.files[0];
		if (!file) return;

		importing.value = true;
		try {
			// Read the file as text
			const xmlContent = await new Promise((resolve, reject) => {
				const reader = new FileReader();
				reader.onload = (e) => resolve(e.target.result);
				reader.onerror = () => reject(new Error("Failed to read file"));
				reader.readAsText(file);
			});

			// Call the backend import endpoint via frappeRequest for consistent
			// CSRF handling, response parsing, and error surfacing.
			const result = await frappeRequest({
				url: "/api/method/processa.api.process_maps.import_bpmn",
				method: "POST",
				params: {
					xml_content: xmlContent,
					// Use the filename (minus .bpmn) as the human-readable title
					title: file.name.replace(/\.bpmn$/i, ""),
					process: props.process || undefined,
				},
			});

			const action = result.action === "updated" ? "updated" : "imported";

			// If the imported map is the one already open, import_bpmn returns the
			// same name and activeDiagramName won't change below, so
			// watch(activeDiagramName) never fires and the canvas would keep
			// showing the stale drawing. Remember this now, before we touch
			// activeDiagramName, so we can repaint it directly further down.
			const isReimportOfOpenDiagram = activeDiagramName.value === result.name;

			// Pre-populate cache so the watch(activeDiagramName) handler
			// gets an instant cache-hit and calls loadXML without a round-trip.
			diagramDataCache.value[result.name] = xmlContent;

			// Reload process diagrams to sync the diagrams list
			await pc.loadProcess();
			let diagramEntry = diagrams.value.find((d) => d.name === result.name);
			if (!diagramEntry) {
				// Not in the process-scoped list - add a synthetic entry so the tab appears
				diagramEntry = {
					name: result.name,
					model_name: result.model_name,
					title: result.model_name,
					process_id: result.process_id,
					is_active: 0,
					status: "Inactive",
				};
				diagrams.value.push(diagramEntry);
			}

			// Only one map is visible at a time - the imported map becomes it.
			openTabs.value = [diagramEntry];

			// Switch to the imported diagram via SPA (no page reload → no Preact crash)
			// The watch(activeDiagramName) picks up the change and calls loadDiagramContent.
			activeDiagramName.value = result.name;
			router.replace({
				name: "DiagramEditor",
				params: { process: props.process, diagram: result.name },
			});

			if (isReimportOfOpenDiagram) {
				// activeDiagramName did not actually change (same name before and
				// after), so the watch(activeDiagramName) above never fires and the
				// canvas is never repainted. Call the load path directly instead -
				// this is a cache-hit thanks to the pre-populated diagramDataCache
				// above, so it just calls editorRef.loadXML with the fresh XML. No
				// page reload (that crashes the Preact properties panel).
				await pc.loadDiagramContent(result.name);
			}

			pc.showNotification(
				"Import Successful",
				`Diagram "${result.model_name}" ${action} successfully.`,
				"green",
			);

			// Run readiness check (informational - does not block)
			await pc.runReadinessCheck(xmlContent, "import");
		} catch (error) {
			console.error("Import failed:", error);
			pc.showNotification(
				"Import Failed",
				error.message || "An unexpected error occurred while importing.",
				"red",
			);
		} finally {
			importing.value = false;
		}
	}

	Object.assign(pc, {
		onConfigImportDone,
		exportCurrentDiagram,
		doExportBpmnOnly,
		doExportWithConfig,
		triggerImport,
		triggerImportConfig,
		handleImportConfigFile,
		handleImportFile,
	});
}
