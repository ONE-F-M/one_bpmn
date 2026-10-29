/** Flags a workflow state update (Apply Workflow) task with no "Only Allow Edit for" role, so the document would not be restricted to a designated role. */

import { is } from "bpmnlint-utils";

import { attr, isExecutable, label } from "../aiShapes.js";

export default function () {
	function check(node, reporter) {
		if (!is(node, "bpmn:ServiceTask") || !isExecutable(node) || attr(node, "serviceType") !== "apply_workflow") {
			return;
		}
		if (String(attr(node, "onlyAllowEdit") || "").trim()) {
			return;
		}
		reporter.report(
			node.id,
			`Workflow state update "${label(node)}" has no "Only Allow Edit for" role. An editable role must be defined.`
		);
	}

	return { check };
}
