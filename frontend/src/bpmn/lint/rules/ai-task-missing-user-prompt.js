/** Flags an AI Agent Task with no user prompt, so the model is asked nothing. */

import { attr, isAiAgent, isExecutable, label } from "../aiShapes.js";

export default function () {
	function check(node, reporter) {
		if (!isAiAgent(node) || !isExecutable(node) || attr(node, "aiUserPrompt")) {
			return;
		}
		reporter.report(node.id, `AI Agent Task "${label(node)}" has no user prompt, so the agent is asked nothing.`);
	}

	return { check };
}
