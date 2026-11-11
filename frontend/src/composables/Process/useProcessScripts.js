import { computed, watch } from "vue";
import { frappeRequest } from "frappe-ui";

export function useProcessScripts(pc) {
	const {
		showScriptEditorDialog,
		scriptEditorTitle,
		scriptDialogMode,
		serverScripts,
		serverScriptSearch,
		selectedServerScript,
		loadingScripts,
		creatingScript,
		previewScriptContent,
		loadingPreview,
		linkedScriptName,
		editScriptContent,
		editScriptMeta,
		loadingEditScript,
		savingEditScript,
		newScript,
		showLogixCanvas,
		logixElement,
		logixScriptType,
		logixCurrentScript,
		logixEventBus,
		logixProcessContext,
		logixReadonly,
		showDeleteScriptConfirm,
		deleteScriptConfirmData,
		doctypeOptions,
		moduleOptions,
		doctypeSearch,
		moduleSearch,
	} = pc;

	// Options for select fields
	const doctypeEvents = [
		"Before Insert",
		"Before Validate",
		"Before Save",
		"After Insert",
		"After Save",
		"Before Rename",
		"After Rename",
		"Before Submit",
		"After Submit",
		"Before Cancel",
		"After Cancel",
		"Before Delete",
		"After Delete",
		"Before Save (Submitted Document)",
		"After Save (Submitted Document)",
		"Before Print",
		"On Payment Authorization",
	];

	const eventFrequencies = [
		"All",
		"Hourly",
		"Daily",
		"Weekly",
		"Monthly",
		"Yearly",
		"Hourly Long",
		"Daily Long",
		"Weekly Long",
		"Monthly Long",
		"Cron",
	];

	// Computed: filtered scripts based on search (restricted to API for Script Tasks)
	const filteredServerScripts = computed(() => {
		let list = serverScripts.value;
		list = list.filter((s) => s.script_type === "API");
		if (!serverScriptSearch.value) return list;
		const q = serverScriptSearch.value.toLowerCase();
		return list.filter(
			(s) =>
				s.name.toLowerCase().includes(q) ||
				(s.script_type && s.script_type.toLowerCase().includes(q)) ||
				(s.reference_doctype && s.reference_doctype.toLowerCase().includes(q)),
		);
	});

	function extractProcessContext(element) {
		if (!element?.businessObject) return null;
		const bo = element.businessObject;
		const mapNode = (ref) =>
			ref
				? {
						id: ref.id,
						name: ref.name || ref.id,
						type: (ref.$type || "").replace("bpmn:", ""),
					}
				: null;
		const incoming = (bo.incoming || []).map((f) => mapNode(f.sourceRef)).filter(Boolean);
		const outgoing = (bo.outgoing || []).map((f) => mapNode(f.targetRef)).filter(Boolean);
		const process = bo.$parent;
		// An element parented by an ad-hoc sub-process is an Agent Tool (it runs via
		// shape_tools' synthetic-task path, not the engine's Script Task path) - the
		// two have different script contracts, so Logix must know which it is writing.
		const parentType = process?.$type || "";
		return {
			element_id: bo.id,
			element_name: bo.name || bo.id,
			element_type: (bo.$type || "").replace("bpmn:", ""),
			process_name: process?.name || process?.id || "",
			parent_type: parentType.replace("bpmn:", ""),
			shape_kind: parentType === "bpmn:AdHocSubProcess" ? "agent_tool" : "script_task",
			incoming,
			outgoing,
		};
	}

	// Computed: filtered DocType options based on search
	const filteredDoctypeOptions = computed(() => {
		if (!doctypeSearch.value) return doctypeOptions.value.slice(0, 50);
		const q = doctypeSearch.value.toLowerCase();
		return doctypeOptions.value.filter((dt) => dt.toLowerCase().includes(q)).slice(0, 50);
	});

	// Computed: filtered Module options based on search
	const filteredModuleOptions = computed(() => {
		if (!moduleSearch.value) return moduleOptions.value.slice(0, 50);
		const q = moduleSearch.value.toLowerCase();
		return moduleOptions.value.filter((m) => m.toLowerCase().includes(q)).slice(0, 50);
	});

	function onLaunchScriptEditor(event) {
		pc.activeScriptEvent = event;

		logixElement.value = event.element;
		logixScriptType.value = event.scriptType || "bpmn:script";
		logixCurrentScript.value = event.script || "";
		logixEventBus.value = event.eventBus;
		logixProcessContext.value = extractProcessContext(event.element);
		logixReadonly.value = !!event.readonly;

		// Prep dialog state so it's ready if the user goes back from Logix
		const typeLabels = {
			"bpmn:script": "Link Server Script",
			"spiffworkflow:PreScript": "Link Pre-Script to Server Script",
			"spiffworkflow:PostScript": "Link Post-Script to Server Script",
		};
		scriptEditorTitle.value = typeLabels[event.scriptType] || "Link Server Script";
		linkedScriptName.value = event.script || "";
		previewScriptContent.value = null;
		loadingPreview.value = false;
		editScriptContent.value = "";
		editScriptMeta.value = { script_type: "", reference_doctype: "" };
		scriptDialogMode.value = event.script ? "edit" : "select";
		serverScriptSearch.value = "";
		selectedServerScript.value = event.script || null;
		if (event.script) loadScriptContent(event.script, "edit");

		// Go straight to Logix canvas - skip the script selector dialog
		showLogixCanvas.value = true;

		// Load server scripts in the background so the dialog is ready if user clicks back
		loadServerScriptsInBackground();
	}

	async function loadServerScriptsInBackground() {
		if (serverScripts.value.length) return;
		loadingScripts.value = true;
		try {
			const response = await frappeRequest({
				url: "/api/method/frappe.client.get_list",
				params: {
					doctype: "Server Script",
					fields: [
						"name",
						"script_type",
						"reference_doctype",
						"disabled",
						"module",
						"modified",
					],
					limit_page_length: 0,
					order_by: "modified desc",
				},
			});
			const data = response.message || response;
			serverScripts.value = Array.isArray(data) ? data : [];
		} catch (e) {
			console.error("Failed to load server scripts:", e);
		} finally {
			loadingScripts.value = false;
		}
	}

	function openLogixCanvas() {
		showScriptEditorDialog.value = false;
		showLogixCanvas.value = true;
	}

	function onLogixBack() {
		showLogixCanvas.value = false;
	}

	function onLogixScriptSaved(scriptName) {
		if (pc.activeScriptEvent && pc.activeScriptEvent.eventBus && scriptName) {
			pc.activeScriptEvent.eventBus.fire("spiff.script.update", {
				element: pc.activeScriptEvent.element,
				scriptType: pc.activeScriptEvent.scriptType,
				script: scriptName,
			});
		}
	}

	function saveScript() {
		if (pc.activeScriptEvent && pc.activeScriptEvent.eventBus && selectedServerScript.value) {
			pc.activeScriptEvent.eventBus.fire("spiff.script.update", {
				element: pc.activeScriptEvent.element,
				scriptType: pc.activeScriptEvent.scriptType,
				script: selectedServerScript.value,
			});
		}
		showScriptEditorDialog.value = false;
		pc.activeScriptEvent = null;
	}

	async function createAndLinkScript() {
		if (!newScript.value.name || !newScript.value.script_type || !newScript.value.script) {
			pc.showNotification(
				"Validation",
				"Script name, type, and content are required.",
				"red",
			);
			return;
		}

		creatingScript.value = true;
		try {
			const result = await frappeRequest({
				url: "one_bpmn.api.server_scripts.create_server_script",
				params: {
					script_name: newScript.value.name,
					script_type: newScript.value.script_type,
					script: newScript.value.script,
					...(newScript.value.reference_doctype && {
						reference_doctype: newScript.value.reference_doctype,
					}),
					...(newScript.value.doctype_event && {
						doctype_event: newScript.value.doctype_event,
					}),
					...(newScript.value.api_method && { api_method: newScript.value.api_method }),
					...(newScript.value.allow_guest && { allow_guest: 1 }),
					...(newScript.value.event_frequency && {
						event_frequency: newScript.value.event_frequency,
					}),
					...(newScript.value.cron_format && {
						cron_format: newScript.value.cron_format,
					}),
					...(newScript.value.module && { module: newScript.value.module }),
				},
			});

			if (pc.activeScriptEvent && pc.activeScriptEvent.eventBus) {
				pc.activeScriptEvent.eventBus.fire("spiff.script.update", {
					element: pc.activeScriptEvent.element,
					scriptType: pc.activeScriptEvent.scriptType,
					script: result.name,
				});
			}
			pc.showNotification(
				"Success",
				`Server Script "${result.name}" created and linked.`,
				"green",
			);
			showScriptEditorDialog.value = false;
			pc.activeScriptEvent = null;
		} catch (error) {
			console.error("Failed to create server script:", error);
			pc.showNotification("Error", "Failed to create: " + (error.message || error), "red");
		} finally {
			creatingScript.value = false;
		}
	}

	async function toggleScriptStatus(script) {
		const newDisabledStatus = script.disabled ? 0 : 1;
		try {
			await frappeRequest({
				url: "one_bpmn.api.server_scripts.toggle_server_script",
				params: {
					script_name: script.name,
					disabled: newDisabledStatus,
				},
			});
			script.disabled = newDisabledStatus;
		} catch (error) {
			console.error("Failed to toggle server script status:", error);
		}
	}

	async function loadScriptContent(scriptName, target) {
		if (!scriptName) return;
		if (target === "preview") {
			loadingPreview.value = true;
			previewScriptContent.value = null;
		} else {
			loadingEditScript.value = true;
		}
		try {
			const response = await frappeRequest({
				url: "/api/method/frappe.client.get",
				params: {
					doctype: "Server Script",
					name: scriptName,
				},
			});
			const doc = response.message || response;
			if (target === "preview") {
				previewScriptContent.value = doc.script || "# (empty script)";
			} else {
				editScriptContent.value = doc.script || "";
				editScriptMeta.value = {
					script_type: doc.script_type || "",
					reference_doctype: doc.reference_doctype || "",
				};
			}
		} catch (error) {
			console.error(`Failed to load script "${scriptName}":`, error);
			if (target === "preview") {
				previewScriptContent.value = "# Failed to load script content";
			}
		} finally {
			if (target === "preview") {
				loadingPreview.value = false;
			} else {
				loadingEditScript.value = false;
			}
		}
	}

	async function saveEditedScript() {
		if (!linkedScriptName.value || !editScriptContent.value) return;
		savingEditScript.value = true;
		try {
			await frappeRequest({
				url: "/api/method/frappe.client.set_value",
				params: {
					doctype: "Server Script",
					name: linkedScriptName.value,
					fieldname: "script",
					value: editScriptContent.value,
				},
			});
			pc.showNotification("Success", `Script "${linkedScriptName.value}" updated.`, "green");
			showScriptEditorDialog.value = false;
			pc.activeScriptEvent = null;
		} catch (error) {
			console.error("Failed to save script:", error);
			pc.showNotification("Error", "Failed to save: " + (error.message || error), "red");
		} finally {
			savingEditScript.value = false;
		}
	}

	watch(selectedServerScript, (newVal) => {
		if (newVal && scriptDialogMode.value === "select") {
			loadScriptContent(newVal, "preview");
		} else {
			previewScriptContent.value = null;
		}
	});

	function onConfirmScriptDelete(payload) {
		// payload: { elements, scriptNames, usageMap, doDelete }
		pc.pendingDeleteElements = payload.elements;
		pc.pendingDeleteModeling = payload.doDelete; // the original removeElements fn
		deleteScriptConfirmData.value = {
			elements: payload.elements,
			scriptNames: payload.scriptNames,
			usageMap: payload.usageMap,
		};
		showDeleteScriptConfirm.value = true;
	}

	async function confirmDeleteElement(alsoDeleteScript) {
		showDeleteScriptConfirm.value = false;
		if (alsoDeleteScript) {
			for (const scriptName of deleteScriptConfirmData.value.scriptNames) {
				try {
					await frappeRequest({
						url: "frappe.client.delete",
						params: { doctype: "Server Script", name: scriptName },
					});
				} catch (e) {
					console.error("Failed to delete script:", scriptName, e);
				}
			}
		}
		// Call the original (pre-intercept) removeElements directly
		if (pc.pendingDeleteModeling && pc.pendingDeleteElements) {
			pc.pendingDeleteModeling(pc.pendingDeleteElements);
		}
		pc.pendingDeleteElements = null;
		pc.pendingDeleteModeling = null;
	}

	Object.assign(pc, {
		doctypeEvents,
		eventFrequencies,
		filteredServerScripts,
		extractProcessContext,
		filteredDoctypeOptions,
		filteredModuleOptions,
		onLaunchScriptEditor,
		loadServerScriptsInBackground,
		openLogixCanvas,
		onLogixBack,
		onLogixScriptSaved,
		saveScript,
		createAndLinkScript,
		toggleScriptStatus,
		loadScriptContent,
		saveEditedScript,
		onConfirmScriptDelete,
		confirmDeleteElement,
	});
}
