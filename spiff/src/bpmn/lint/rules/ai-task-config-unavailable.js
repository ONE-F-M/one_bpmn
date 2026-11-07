/** Flags an AI task linked to an AI Agent Configuration that was deleted or is switched off. */

import { linkedConfig } from "../agentConfigState.js";
import { label } from "../aiShapes.js";

export default function () {
	function check(node, reporter) {
		const { name, state } = linkedConfig(node) || {};
		if (!state || (state.exists && state.enabled)) {
			return;
		}
		const problem = state.exists ? "is disabled" : "was not found";
		reporter.report(node.id, `AI Agent Configuration "${name}" ${problem} (task "${label(node)}").`);
	}

	return { check };
}
