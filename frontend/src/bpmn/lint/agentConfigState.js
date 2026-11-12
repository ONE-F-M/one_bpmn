/** What the editor knows about each linked AI Agent Configuration, filled in by useAgentConfigLintState. */

import { attr, isAiAgent, isAiSelector, isExecutable } from "./aiShapes.js";

const states = new Map();

export function agentConfigState(name) {
	return states.get(name);
}

export function storeAgentConfigStates(byName) {
	for (const [name, state] of Object.entries(byName)) {
		states.set(name, state);
	}
}

/** The configuration an AI shape links to and what is known about it, or null while that is unknown. */
export function linkedConfig(node) {
	if (!(isAiAgent(node) || isAiSelector(node)) || !isExecutable(node)) {
		return null;
	}
	const name = attr(node, "aiAgentConfig");
	const state = name && states.get(name);
	return state ? { name, state } : null;
}
