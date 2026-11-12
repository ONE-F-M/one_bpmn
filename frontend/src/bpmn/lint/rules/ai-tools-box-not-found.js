/** Flags an AI Agent Task whose aiToolsAdhoc names no ad-hoc sub-process in the process. */

import { adHocSubProcessIds, attr, isAiAgent, isExecutable, label } from "../aiShapes.js";

export default function () {
	function check(node, reporter) {
		const boxId = isAiAgent(node) ? attr(node, "aiToolsAdhoc") : "";
		if (!boxId || !isExecutable(node) || adHocSubProcessIds(node).has(boxId)) {
			return;
		}
		reporter.report(
			node.id,
			`AI Agent Task "${label(node)}" points at "${boxId}" for its tools, but no ad-hoc sub-process has that id.`
		);
	}

	return { check };
}
