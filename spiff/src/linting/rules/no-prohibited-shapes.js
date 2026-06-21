/**
 * Custom bpmnlint rule: no-prohibited-shapes
 *
 * Flags BPMN element types that OneFM prohibits in **executable** processes.
 * Non-executable (documentation-only) processes are exempt — the rule silently
 * passes for any node that does not live inside a process with isExecutable=true.
 *
 * IMPORTANT: We use exact $type matching (node.$type === "bpmn:Task") instead
 * of bpmnlint-utils `is()` because `is()` checks type *hierarchy* — meaning
 * is(userTask, "bpmn:Task") returns true since UserTask extends Task.
 * We only want to flag the generic "None-type" Task, not its subtypes.
 *
 * The prohibited shapes map mirrors the backend constant in
 *   one_bpmn/api/compilation.py → PROHIBITED_SHAPES
 * Keep both in sync when adding or removing entries.
 */

import { is } from "bpmnlint-utils";

/**
 * Map of exact BPMN $type → { label, suggestion }.
 * Keys must match the moddle element's $type property exactly.
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
 *   1. The element's exact $type is in PROHIBITED_SHAPES
 *   2. The element is inside a bpmn:Process with isExecutable === true
 */
export default function () {
	function check(node, reporter) {
		// Use exact $type match — NOT is()/isAny() which check inheritance.
		// is(userTask, "bpmn:Task") would be true because UserTask extends Task.
		const exactType = node.$type;
		const info = PROHIBITED_SHAPES[exactType];
		if (!info) {
			return;
		}

		// Only enforce in executable processes
		const process = findParentProcess(node);
		if (!process || !process.isExecutable) {
			return;
		}

		const name = node.name ? ` "${node.name}"` : "";
		reporter.report(
			node.id,
			`${info.label}${name} is not allowed in executable processes. ${info.suggestion}.`
		);
	}

	return { check };
}
