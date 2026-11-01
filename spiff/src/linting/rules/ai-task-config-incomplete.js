/** Flags an AI task linked to an AI Agent Configuration that lacks a setting every run needs. */

import { linkedConfig } from "../agentConfigState.js";
import { label } from "../aiShapes.js";

export default function () {
	function check(node, reporter) {
		const { name, state } = linkedConfig(node) || {};
		if (!state?.exists || !state.problems?.length) {
			return;
		}
		reporter.report(
			node.id,
			`AI Agent Configuration "${name}" is not set up (task "${label(node)}"): ${state.problems.join(" ")}`
		);
	}

	return { check };
}
