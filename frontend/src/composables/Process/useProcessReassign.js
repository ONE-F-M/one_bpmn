import { watch } from "vue";
import { frappeRequest } from "frappe-ui";

export function useProcessReassign(pc) {
	const { activeDiagramName, reassignMode, pendingReassignments, touchedReassignModels } = pc;

	function toggleReassignMode() {
		if (reassignMode.value) {
			// Turning OFF → persist anything pending, then deploy once.
			reassignMode.value = false;
			pc.showNotification(
				"Property panel locked",
				"All locked in, we're back to read-only mode.",
				"gray",
			);
			finalizeReassignments();
		} else {
			reassignMode.value = true;
			touchedReassignModels.clear();
			pc.showNotification(
				"Property panel released",
				"Properties of flow objects can now be modified, except for script tasks and AI Agent tasks.",
				"blue",
			);
		}
	}

	// Leaving the diagram (or previewing a version) exits reassign mode - finalize
	// so the session's edits are still deployed in one pass.
	watch(activeDiagramName, () => {
		if (reassignMode.value) {
			reassignMode.value = false;
			finalizeReassignments();
		}
	});

	function onReassignChanged({ taskId, assignment }) {
		if (!activeDiagramName.value || !taskId) return;
		pendingReassignments.set(taskId, {
			modelName: activeDiagramName.value,
			assignment,
		});
		if (pc.reassignSaveTimer) clearTimeout(pc.reassignSaveTimer);
		pc.reassignSaveTimer = setTimeout(flushReassignments, 1200);
	}

	// Persist pending per-task changes. Saving is what records them in the map's
	// version history. Does NOT deploy - that is batched into
	// finalizeReassignments().
	async function flushReassignments() {
		if (pc.reassignSaveTimer) {
			clearTimeout(pc.reassignSaveTimer);
			pc.reassignSaveTimer = null;
		}
		const entries = [...pendingReassignments.entries()];
		pendingReassignments.clear();
		for (const [taskId, { modelName, assignment }] of entries) {
			try {
				const res = await frappeRequest({
					url: "/api/method/processa.api.property_panel.update_element_properties",
					method: "POST",
					params: {
						model_name: modelName,
						element_id: taskId,
						properties: JSON.stringify(assignment),
					},
				});
				if (res && res.updated) touchedReassignModels.add(modelName);
			} catch (err) {
				const msg =
					err.messages && err.messages.length
						? err.messages.join("\n")
						: err.message || "Failed to save the property change.";
				pc.showNotification("Property change failed", msg, "red", true);
			}
		}
	}

	// Flush any pending change, then recompile each touched model exactly once.
	async function finalizeReassignments() {
		await flushReassignments();
		if (!touchedReassignModels.size) return;

		const models = [...touchedReassignModels];
		touchedReassignModels.clear();

		let deployFailed = false;
		for (const modelName of models) {
			try {
				const res = await frappeRequest({
					url: "/api/method/processa.api.property_panel.deploy_property_changes",
					method: "POST",
					params: { model_name: modelName },
				});
				if (!res || res.deploy_error) deployFailed = true;
			} catch {
				deployFailed = true;
			}
		}

		// Locking the panel already announced itself; only a failed redeploy needs a word.
		if (deployFailed) {
			pc.showNotification(
				"Changes saved, redeploy pending",
				"Property changes were saved and recorded in the version history, but automatic redeploy failed. Click Deploy to apply them to new instances.",
				"red",
				true,
			);
		}
	}

	Object.assign(pc, {
		toggleReassignMode,
		onReassignChanged,
		flushReassignments,
		finalizeReassignments,
	});
}
