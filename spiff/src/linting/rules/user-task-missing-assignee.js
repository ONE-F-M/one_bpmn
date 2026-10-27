/** Flags a User Task whose Assignee Mode has no value to assign from, so the task is left unassigned. */

import { is } from "bpmnlint-utils";

import { attr, isExecutable, label } from "../aiShapes.js";

const ASSIGNEE_FIELD = {
	User: ["assigneeUser", "user"],
	DocField: ["assigneeDocfield", "document field"],
	"Round Robin": ["assigneeUsers", "list of users"],
	"Load Balancing": ["assigneeUsers", "list of users"],
	"Table Field": ["assigneeTableField", "table field"],
};

export default function () {
	function check(node, reporter) {
		if (!is(node, "bpmn:UserTask") || !isExecutable(node)) {
			return;
		}
		const mode = attr(node, "assigneeMode");
		const [field, noun] = ASSIGNEE_FIELD[mode] || [];
		if (field && !attr(node, field)) {
			reporter.report(node.id, `User Task "${label(node)}" assigns by ${mode} but its ${noun} is empty, so it is left unassigned.`);
		}
	}

	return { check };
}
