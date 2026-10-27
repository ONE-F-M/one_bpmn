import { frappeRequest } from "frappe-ui";

import { agentConfigState, storeAgentConfigStates } from "@/linting/agentConfigState.js";

const RELINT_DELAY_MS = 800;

/** Loads the named configurations' lifecycle and setup gaps; true when anything arrived. */
export async function loadAgentConfigStates(names, { refresh = false } = {}) {
	const wanted = refresh ? names : names.filter((name) => !agentConfigState(name));
	if (!wanted.length) {
		return false;
	}
	const states = await frappeRequest({
		url: "/api/method/one_bpmn.agents.agent_config_resolver.get_agent_config_lint_state",
		method: "POST",
		params: { config_names: JSON.stringify(wanted) },
	});
	storeAgentConfigStates(states);
	return true;
}

function linkedConfigNames(modeler) {
	const names = modeler
		.get("elementRegistry")
		.getAll()
		.map((element) => String(element.businessObject?.get?.("spiffworkflow:aiAgentConfig") || "").trim());
	return [...new Set(names.filter(Boolean))];
}

/** Keeps the linter's view of linked configurations current: all of them on import, new ones after edits. */
export function watchAgentConfigLint(modeler) {
	const eventBus = modeler.get("eventBus");
	const linting = modeler.get("linting");
	let timer = null;

	async function refresh(refreshAll) {
		try {
			if (await loadAgentConfigStates(linkedConfigNames(modeler), { refresh: refreshAll })) {
				linting.update();
			}
		} catch {
			// A user who cannot read configurations leaves them unknown, so the config rules stay quiet.
		}
	}

	eventBus.on("import.done", () => refresh(true));
	eventBus.on("commandStack.changed", () => {
		clearTimeout(timer);
		timer = setTimeout(() => refresh(false), RELINT_DELAY_MS);
	});
}
