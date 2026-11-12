/** Flags an AI task linked to an enabled AI Agent Configuration that is not Live, which deploy refuses. */

import { linkedConfig } from "../agentConfigState.js";
import { label } from "../aiShapes.js";

export default function () {
	function check(node, reporter) {
		const { name, state } = linkedConfig(node) || {};
		if (!state?.exists || !state.enabled || state.lifecycle_status === "Live") {
			return;
		}
		reporter.report(
			node.id,
			`AI Agent Configuration "${name}" is ${state.lifecycle_status} (task "${label(node)}"). It must be Live before deploy.`
		);
	}

	return { check };
}
