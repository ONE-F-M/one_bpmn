/**
 * Custom bpmnlint rule: script-task-missing-script
 *
 * Flags a Script Task in an executable process that has neither a linked
 * Server Script nor an inline script, since it does nothing when it runs.
 */

import { is } from "bpmnlint-utils";

function inExecutableProcess(node) {
	let current = node.$parent;
	while (current && !is(current, "bpmn:Process")) {
		current = current.$parent;
	}
	return Boolean(current && current.isExecutable);
}

export default function () {
	function check(node, reporter) {
		if (!is(node, "bpmn:ScriptTask") || !inExecutableProcess(node)) {
			return;
		}
		const serverScript = node.get("spiffworkflow:serverScript") || (node.$attrs || {})["spiffworkflow:serverScript"];
		if (String(serverScript || "").trim() || String(node.script || "").trim()) {
			return;
		}
		const name = node.name ? ` "${node.name}"` : "";
		reporter.report(
			node.id,
			`Script Task${name} has no script. Pick a Server Script or write one with Logix.`
		);
	}

	return { check };
}
