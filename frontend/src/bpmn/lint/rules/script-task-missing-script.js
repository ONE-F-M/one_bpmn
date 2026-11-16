/**
 * Custom bpmnlint rule: script-task-missing-script
 *
 * Flags a Script Task in an executable process that has neither a linked
 * Server Script nor an inline script, since it does nothing when it runs.
 */

import { is } from "bpmnlint-utils";

import { findParentProcess } from "./call-activity-missing-process.js";

export default function () {
	function check(node, reporter) {
		if (!is(node, "bpmn:ScriptTask") || !findParentProcess(node)?.isExecutable) {
			return;
		}
		const serverScript = node.get("spiffworkflow:serverScript");
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
