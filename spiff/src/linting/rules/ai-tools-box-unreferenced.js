/** Flags an unconnected ad-hoc sub-process of tool shapes that no AI Agent Task uses. */

import { is } from "bpmnlint-utils";

import { isAiSelector, isExecutable, label, toolBoxIds, toolShapes } from "../aiShapes.js";

export default function () {
	function check(node, reporter) {
		if (!is(node, "bpmn:AdHocSubProcess") || isAiSelector(node) || !isExecutable(node)) {
			return;
		}
		if ((node.incoming || []).length || (node.outgoing || []).length || toolBoxIds(node).has(node.id)) {
			return;
		}
		if (!toolShapes(node).length) {
			return;
		}
		reporter.report(
			node.id,
			`Ad-hoc sub-process "${label(node)}" holds tool shapes, but no AI Agent Task uses it as its Tools box.`
		);
	}

	return { check };
}
