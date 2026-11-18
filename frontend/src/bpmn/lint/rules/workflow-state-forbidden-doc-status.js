/** Flags a workflow state update whose document status cannot follow the previous one on the same doctype, by Frappe's docstatus rules. */

import { is } from "bpmnlint-utils";

import { attr, isExecutable, label } from "../aiShapes.js";

const STATUS_LABELS = { 0: "Draft", 1: "Submitted", 2: "Cancelled" };

// Frappe allows 0 to 0, 0 to 1, 1 to 1 and 1 to 2; a cancelled document cannot change.
const FORBIDDEN = new Set(["0>2", "1>0", "2>0", "2>1", "2>2"]);

export default function () {
	function check(node, reporter) {
		if (!isApplyWorkflow(node) || !isExecutable(node)) {
			return;
		}
		const from = attr(node, "docStatus");
		for (const next of nextApplyWorkflows(node)) {
			const to = attr(next, "docStatus");
			if (FORBIDDEN.has(`${from}>${to}`)) {
				reporter.report(
					next.id,
					`"${label(next)}" sets the document to ${statusLabel(to)} right after "${label(node)}" set it to ${statusLabel(from)}. Frappe does not allow ${statusLabel(from)} to ${statusLabel(to)}.`
				);
			}
		}
	}

	return { check };
}

function isApplyWorkflow(node) {
	return is(node, "bpmn:ServiceTask") && attr(node, "serviceType") === "apply_workflow";
}

function statusLabel(status) {
	return `${STATUS_LABELS[status]} (${status})`;
}

/** The workflow state updates on the same doctype reachable from node without passing another one. */
function nextApplyWorkflows(node) {
	const doctype = attr(node, "serviceTargetDoctype");
	const found = [];
	const seen = new Set([node]);
	const queue = successors(node);
	while (queue.length) {
		const current = queue.shift();
		if (seen.has(current)) {
			continue;
		}
		seen.add(current);
		if (isApplyWorkflow(current) && attr(current, "serviceTargetDoctype") === doctype) {
			found.push(current);
			continue;
		}
		queue.push(...successors(current));
	}
	return found;
}

function successors(node) {
	return node.$parent.flowElements
		.map((element) => {
			if (is(element, "bpmn:SequenceFlow") && element.sourceRef === node) {
				return element.targetRef;
			}
			return is(element, "bpmn:BoundaryEvent") && element.attachedToRef === node ? element : null;
		})
		.filter(Boolean);
}
