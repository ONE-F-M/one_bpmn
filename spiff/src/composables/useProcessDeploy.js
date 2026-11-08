import { frappeRequest } from "frappe-ui";
import { withLintErrors } from "@/utils/lintIssues.js";

export function useProcessDeploy(pc) {
	const {
		editorRef,
		diagrams,
		activeDiagramName,
		deploying,
		disabling,
		showDisableDialog,
		disableRunningCount,
		showNonExecutableDialog,
		nonExecutableActivating,
		nonExecutableBusy,
		isExecutable,
		showReadinessDialog,
		readinessChecklist,
		readinessMode,
		readinessLoading,
		importConfigFileInput,
		activeVersionName,
	} = pc;

	// Readiness check (shared by import & deploy)
	async function runReadinessCheck(xmlContent, mode) {
		readinessMode.value = mode;
		readinessChecklist.value = null;
		readinessLoading.value = true;
		showReadinessDialog.value = true;
		pc.lastReadinessXml = xmlContent; // Store for recheck after config import

		try {
			const params = { xml_content: xmlContent };
			// When deploying, pass model_name so the backend can check for
			// call activity references to sibling models that will be disabled.
			if (mode === "deploy" && activeDiagramName.value) {
				params.model_name = activeDiagramName.value;
			}
			const response = await frappeRequest({
				url: "/api/method/one_bpmn.api.process_map_api.validate_bpmn_readiness",
				params,
			});
			const checklist = response.message || response;
			readinessChecklist.value =
				mode === "deploy"
					? withLintErrors(checklist, await editorRef.value?.getRawLintIssues())
					: checklist;
		} catch (err) {
			console.error("Readiness check failed:", err);
			readinessChecklist.value = {
				categories: [
					{
						label: "Readiness Check Error",
						items: [
							{
								label: "Unable to validate BPMN readiness",
								status: "missing",
								message:
									"The readiness check failed. Please retry before importing or deploying.",
							},
						],
					},
				],
				total_checked: 1,
				total_missing: 1,
				total_warnings: 0,
				all_ready: false,
			};
		} finally {
			readinessLoading.value = false;
		}
	}

	function onReadinessClose() {
		showReadinessDialog.value = false;
	}

	function onReadinessCancel() {
		showReadinessDialog.value = false;
	}

	async function onReadinessDeploy() {
		showReadinessDialog.value = false;
		await executeDeployment();
	}

	// Upload config from readiness dialog (opens file picker)
	function onReadinessUploadConfig() {
		if (importConfigFileInput.value) {
			importConfigFileInput.value.value = "";
			importConfigFileInput.value.click();
		}
	}

	// Recheck readiness after config import
	async function onReadinessRecheck() {
		if (pc.lastReadinessXml) {
			await runReadinessCheck(pc.lastReadinessXml, readinessMode.value);
		}
	}

	// Update all call activity references and recheck
	async function onReadinessUpdateRefs(refItems) {
		if (!refItems || refItems.length === 0) return;

		readinessLoading.value = true;
		try {
			const response = await frappeRequest({
				url: "/api/method/one_bpmn.api.process_map_api.update_call_activity_references",
				method: "POST",
				params: { references: JSON.stringify(refItems) },
			});

			const result = response.message || response;
			pc.showNotification(
				"References Updated",
				`Updated ${result.updated || 0} call activity reference(s).`,
				"green",
			);

			// Recheck readiness to confirm the refs are resolved
			if (pc.lastReadinessXml) {
				await runReadinessCheck(pc.lastReadinessXml, readinessMode.value);
			}
		} catch (err) {
			const serverMessage =
				err.messages && err.messages.length > 0
					? err.messages.join("\n")
					: err.message || "An error occurred while updating references.";
			pc.showNotification("Update Failed", serverMessage, "red", true);
			readinessLoading.value = false;
		}
	}

	// Deploy (compile) the process model
	async function deployModel() {
		if (!activeDiagramName.value || deploying.value) return;
		if (activeVersionName.value) {
			pc.showNotification(
				"Deploy",
				"You're viewing a read-only version. Switch to the latest version to deploy.",
				"red",
			);
			return;
		}

		if (!isExecutable.value) {
			nonExecutableActivating.value = true;
			showNonExecutableDialog.value = true;
			return;
		}

		// Get current XML for readiness check
		let xml = "";
		if (editorRef.value) {
			xml = await editorRef.value.getXML();
		}
		if (!xml) {
			pc.showNotification("Deploy", "No diagram XML found.", "red");
			return;
		}

		// Run readiness check - dialog handles the rest
		await runReadinessCheck(xml, "deploy");
	}

	// Actual deployment (called after readiness check passes)
	async function executeDeployment() {
		if (!activeDiagramName.value || deploying.value) return;
		if (activeVersionName.value) return; // Guard: previewing a read-only version

		deploying.value = true;
		try {
			const response = await frappeRequest({
				url: "/api/method/one_bpmn.api.deploy.compile_process_model",
				method: "POST",
				params: { model_name: activeDiagramName.value },
			});

			if (response && response.success) {
				pc.showNotification(
					"Deployed",
					`Deployed successfully — version ${response.version}, ${response.subprocess_count} subprocess(es)`,
					"green",
				);

				// Show deploy readiness warnings (non-blocking). Warnings may be
				// plain strings (eval suite gating) or structured objects with
				// { label, detail, type, icon } (e.g. backend code removal).
				// All of them in ONE banner: the banner holds a single message, so
				// raising them one by one left only the last one on screen.
				if (response.warnings && response.warnings.length > 0) {
					const lines = response.warnings.map((warning) =>
						warning && typeof warning === "object"
							? `${warning.label ? warning.label + ": " : ""}${warning.detail || warning.label || ""}`
							: `Eval Suite: ${warning}`,
					);
					pc.showNotification(
						lines.length === 1 ? "Deploy Warning" : `${lines.length} Deploy Warnings`,
						lines.join("\n\n"),
						"orange",
						true,
					);
				}

				// Update local state: mark this diagram as active, deactivate siblings
				for (const d of diagrams.value) {
					if (d.name === activeDiagramName.value) {
						d.is_active = 1;
						d.status = "Active";
						d.version = response.version;
					} else {
						d.is_active = 0;
						d.status = "Inactive";
					}
				}
			} else {
				pc.showNotification("Deploy", "Deployment completed", "green");
			}
		} catch (err) {
			const serverMessage =
				err.messages && err.messages.length > 0
					? err.messages.join("\n")
					: err.message || "An error occurred while deploying the process model.";
			pc.showNotification("Deploy Failed", serverMessage, "red", true);
		} finally {
			deploying.value = false;
		}
	}

	// Disable a deployed process model (inverse of deploy)
	async function disableModel() {
		if (!activeDiagramName.value || disabling.value) return;

		if (!isExecutable.value) {
			nonExecutableActivating.value = false;
			showNonExecutableDialog.value = true;
			return;
		}

		// Fetch running instance count for the confirmation dialog
		disableRunningCount.value = 0;
		try {
			const countResp = await frappeRequest({
				url: "/api/method/frappe.client.get_count",
				method: "GET",
				params: {
					doctype: "BPMN Process Instance",
					filters: JSON.stringify({
						process_model: activeDiagramName.value,
						status: ["in", ["Running", "Waiting"]],
					}),
				},
			});
			disableRunningCount.value = countResp || 0;
		} catch {
			// Non-fatal - dialog will simply not show the count
		}

		showDisableDialog.value = true;
	}

	// Actual disable execution (called from confirmation dialog)
	async function executeDisable() {
		if (!activeDiagramName.value || disabling.value) return;

		disabling.value = true;
		try {
			const response = await frappeRequest({
				url: "/api/method/one_bpmn.api.deploy.disable_process_model",
				method: "POST",
				params: { model_name: activeDiagramName.value },
			});

			showDisableDialog.value = false;

			if (response && response.success) {
				const runningMsg = response.running_instances
					? ` ${response.running_instances} running instance(s) will continue.`
					: "";
				pc.showNotification(
					"Disabled",
					`Process map disabled successfully.${runningMsg}`,
					"orange",
				);

				// Update local state
				for (const d of diagrams.value) {
					if (d.name === activeDiagramName.value) {
						d.is_active = 0;
						d.status = "Inactive";
					}
				}
			}
		} catch (err) {
			showDisableDialog.value = false;
			const serverMessage =
				err.messages && err.messages.length > 0
					? err.messages.join("\n")
					: err.message || "An error occurred while disabling the process map.";
			pc.showNotification("Disable Failed", serverMessage, "red", true);
		} finally {
			disabling.value = false;
		}
	}

	// Activate or deactivate a non-executable process model (called from its confirmation dialog)
	async function executeNonExecutableToggle() {
		if (!activeDiagramName.value || nonExecutableBusy.value) return;

		const activating = nonExecutableActivating.value;
		nonExecutableBusy.value = true;
		try {
			await frappeRequest({
				url: `/api/method/one_bpmn.api.deploy.${activating ? "activate" : "deactivate"}_non_executable_model`,
				method: "POST",
				params: { model_name: activeDiagramName.value },
			});

			showNonExecutableDialog.value = false;
			pc.showNotification(
				activating ? "Deployed" : "Disabled",
				activating ? "Process model marked active." : "Process model marked inactive.",
				activating ? "green" : "orange",
			);

			for (const d of diagrams.value) {
				if (d.name === activeDiagramName.value) {
					d.is_active = activating ? 1 : 0;
					d.status = activating ? "Active" : "Inactive";
				} else if (activating) {
					d.is_active = 0;
					d.status = "Inactive";
				}
			}
		} catch (err) {
			showNonExecutableDialog.value = false;
			const serverMessage =
				err.messages && err.messages.length > 0
					? err.messages.join("\n")
					: err.message || "An error occurred while updating the process model.";
			pc.showNotification(
				activating ? "Deploy Failed" : "Disable Failed",
				serverMessage,
				"red",
				true,
			);
		} finally {
			nonExecutableBusy.value = false;
		}
	}

	Object.assign(pc, {
		runReadinessCheck,
		onReadinessClose,
		onReadinessCancel,
		onReadinessDeploy,
		onReadinessUploadConfig,
		onReadinessRecheck,
		onReadinessUpdateRefs,
		deployModel,
		executeDeployment,
		disableModel,
		executeDisable,
		executeNonExecutableToggle,
	});
}
