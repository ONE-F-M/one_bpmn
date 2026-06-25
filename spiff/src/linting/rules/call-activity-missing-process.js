/**
 * Custom bpmnlint rule: call-activity-missing-process
 *
 * Flags Call Activity elements that do not have a linked (called) process.
 * A Call Activity without a `calledElement` attribute is incomplete and will
 * fail at execution time because the engine won't know which process to invoke.
 *
 * Only enforced in executable processes — non-executable (documentation-only)
 * processes are exempt.
 */

import { is } from "bpmnlint-utils";

/**
 * Walk up the $parent chain to find the enclosing bpmn:Process.
 *
 * @param {ModdleElement} node
 * @returns {ModdleElement|null}
 */
function findParentProcess(node) {
	let current = node;
	while (current) {
		if (is(current, "bpmn:Process")) {
			return current;
		}
		current = current.$parent;
	}
	return null;
}

/**
 * Rule factory.
 *
 * Returns a check function that reports a warning when ALL of the following
 * are true:
 *   1. The element is a bpmn:CallActivity
 *   2. The element is inside a bpmn:Process with isExecutable === true
 *   3. The element has no `calledElement` attribute (or it is empty)
 */
export default function () {
	function check(node, reporter) {
		if (node.$type !== "bpmn:CallActivity") {
			return;
		}

		// Only enforce in executable processes
		const process = findParentProcess(node);
		if (!process || !process.isExecutable) {
			return;
		}

		const calledElement = node.calledElement;
		if (!calledElement || !calledElement.trim()) {
			const name = node.name ? ` "${node.name}"` : "";
			reporter.report(
				node.id,
				`Call Activity${name} has no linked process. Use the search dialog to link it to an existing process.`
			);
		}
	}

	return { check };
}
