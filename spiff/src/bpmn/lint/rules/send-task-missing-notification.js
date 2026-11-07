/** Flags a Send Task with no Notification chosen, since it sends nothing when it runs. */

import { is } from "bpmnlint-utils";

import { attr, isExecutable, label } from "../aiShapes.js";

export default function () {
	function check(node, reporter) {
		if (!is(node, "bpmn:SendTask") || !isExecutable(node) || attr(node, "notificationName")) {
			return;
		}
		reporter.report(node.id, `Send Task "${label(node)}" has no Notification selected, so it sends nothing.`);
	}

	return { check };
}
