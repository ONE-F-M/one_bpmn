/**
 * Flags an AI Agent Task or AI Task Selector with no linked AI Agent Configuration,
 * which deploy refuses.
 */

import { attr, isAiAgent, isAiSelector, isExecutable, label } from "../aiShapes.js";

export default function () {
	function check(node, reporter) {
		if (!(isAiAgent(node) || isAiSelector(node)) || !isExecutable(node) || attr(node, "aiAgentConfig")) {
			return;
		}
		reporter.report(
			node.id,
			`AI task "${label(node)}" has no AI Agent Configuration. Link an existing agent or create one from the task dialog.`
		);
	}

	return { check };
}
