// Creating a Workflow Action Master from a User Task's action row, kept free of the panel's imports so node --test can load it.

// Resolves to the created action's name; the caller passes trimmed, non-blank text.
export function createWorkflowActionMaster(post, name) {
	// Workflow Action Master is named by workflow_action_name, so the record is always called what was typed.
	return post("/api/resource/Workflow Action Master", { workflow_action_name: name }).then(() => name);
}
