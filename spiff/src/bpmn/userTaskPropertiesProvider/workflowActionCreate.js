// Creating a Workflow Action Master from a User Task's action row, kept free of the panel's imports so node --test can load it.

// Returns null for a blank name without calling post; otherwise a promise of the created action's name.
export function createWorkflowActionMaster(post, workflowActionName) {
	const name = workflowActionName.trim();
	if (!name) return null;
	// Workflow Action Master is named by workflow_action_name, so the record is always called what was typed.
	return post("/api/resource/Workflow Action Master", { workflow_action_name: name }).then(() => name);
}
