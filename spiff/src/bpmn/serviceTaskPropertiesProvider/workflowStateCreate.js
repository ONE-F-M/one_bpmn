// Creating a Workflow State from the Apply Workflow panel, kept free of the panel's imports so node --test can load it.

export const WORKFLOW_STATE_STYLES = ["Primary", "Info", "Success", "Warning", "Danger", "Inverse"];

// Returns null for a blank name without calling post; otherwise a promise of the created state's name.
export function createWorkflowState(post, workflowStateName, style) {
	const name = workflowStateName.trim();
	if (!name) return null;
	// Workflow State is named by workflow_state_name, so the record is always called what was typed.
	return post("/api/resource/Workflow State", { workflow_state_name: name, style }).then(() => name);
}

// States whose name contains the query, and whether the typed name is new enough to offer creating it.
export function filterWorkflowStates(states, query) {
	const q = (query || "").trim().toLowerCase();
	const matches = q ? states.filter((s) => s.name.toLowerCase().includes(q)) : states;
	return { matches, canCreate: !!q && !states.some((s) => s.name.toLowerCase() === q) };
}
