/**
 * Custom bpmnlint rule: no-prohibited-shapes
 *
 * Flags BPMN element types that OneFM prohibits in **executable** processes.
 * Non-executable (documentation-only) processes are exempt — the rule silently
 * passes for any node that does not live inside a process with isExecutable=true.
 *
 * The prohibited shapes map mirrors the backend constant in
 *   one_bpmn/api/compilation.py → PROHIBITED_SHAPES
 * Keep both in sync when adding or removing entries.
 */

import { is, isAny } from "bpmnlint-utils";

/**
 * Map of BPMN type → { label, suggestion }.
 * The keys use the fully-qualified bpmn: prefix that bpmnlint-utils `is()` expects.
 */
const PROHIBITED_SHAPES = {
	"bpmn:ManualTask": {
		label: "Manual Task",
		suggestion: "Use a User Task instead",
	},
	"bpmn:Task": {
		label: "None-type Task",
		suggestion: "Use a User Task instead",
	},
};

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
 * Returns a check function that is called for every element in the diagram.
 * It only reports when ALL of the following are true:
 *   1. The element's type is in PROHIBITED_SHAPES
 *   2. The element is inside a bpmn:Process with isExecutable === true
 */
export default function () {
	const prohibitedTypes = Object.keys(PROHIBITED_SHAPES);

	function check(node, reporter) {
		// Only inspect nodes that match a prohibited type
		if (!isAny(node, prohibitedTypes)) {
			return;
		}

		// Only enforce in executable processes
		const process = findParentProcess(node);
		if (!process || !process.isExecutable) {
			return;
		}

		// Find which specific type matched (for the right label/message)
		for (const [type, info] of Object.entries(PROHIBITED_SHAPES)) {
			if (is(node, type)) {
				const name = node.name ? ` "${node.name}"` : "";
				reporter.report(
					node.id,
					`${info.label}${name} is not allowed in executable processes. ${info.suggestion}.`
				);
				break;
			}
		}
	}

	return { check };
}
