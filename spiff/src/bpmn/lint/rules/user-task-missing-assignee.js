/** Flags a User Task with no Assignment Mode, no Task Action, or an Assignment Mode with no value to assign from. */

import { is } from "bpmnlint-utils";

import { attr, isExecutable, label } from "../aiShapes.js";

const ASSIGNEE_FIELD = {
	User: ["assigneeUser", "user"],
	DocField: ["assigneeDocfield", "document field"],
	"Round Robin": ["assigneeUsers", "list of users"],
	"Load Balancing": ["assigneeUsers", "list of users"],
	"Table Field": ["assigneeTableField", "table field"],
};

function hasTaskAction(node) {
	try {
		const actions = JSON.parse(attr(node, "taskActions") || "[]");
		return Array.isArray(actions) && actions.some((row) => String(row?.action || "").trim());
	} catch {
		return false;
	}
}

export default function () {
	function check(node, reporter) {
		if (!is(node, "bpmn:UserTask") || !isExecutable(node)) {
			return;
		}
		const mode = attr(node, "assigneeMode");
		if (!mode) {
			reporter.report(node.id, `User Task "${label(node)}" requires an Assignment Mode.`);
		}
		if (!hasTaskAction(node)) {
			reporter.report(node.id, `User Task "${label(node)}" requires at least one Task Action.`);
		}
		const [field, noun] = ASSIGNEE_FIELD[mode] || [];
		if (field && !attr(node, field)) {
			reporter.report(node.id, `User Task "${label(node)}" assigns by ${mode} but its ${noun} is empty, so it is left unassigned.`);
		}
	}

	return { check };
}
