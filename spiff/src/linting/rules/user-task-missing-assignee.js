/** Flags a User Task whose Assignee Mode has no value to assign from, so the task is left unassigned. */

import { is } from "bpmnlint-utils";

import { attr, isExecutable, label } from "../aiShapes.js";

const ASSIGNEE_FIELD = {
	User: ["assigneeUser", "a user"],
	DocField: ["assigneeDocfield", "a document field"],
	"Round Robin": ["assigneeUsers", "users"],
	"Load Balancing": ["assigneeUsers", "users"],
	"Table Field": ["assigneeTableField", "a table field"],
};

export default function () {
	function check(node, reporter) {
		if (!is(node, "bpmn:UserTask") || !isExecutable(node)) {
			return;
		}
		const mode = attr(node, "assigneeMode");
		const [field, noun] = ASSIGNEE_FIELD[mode] || [];
		if (field && !attr(node, field)) {
			reporter.report(node.id, `User Task "${label(node)}" assigns by ${mode} but no ${noun} is set, so it is left unassigned.`);
		}
	}

	return { check };
}
