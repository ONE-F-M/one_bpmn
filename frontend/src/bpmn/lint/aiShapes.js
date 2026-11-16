/** Helpers the AI lint rules share: finding AI shapes, their Tools box and its tool shapes. */

import { is } from "bpmnlint-utils";

import { findParentProcess } from "./rules/call-activity-missing-process.js";

const AUTOMATIC_TOOL_TYPES = ["bpmn:ScriptTask", "bpmn:ServiceTask"];
const HUMAN_TOOL_TYPES = ["bpmn:UserTask", "bpmn:ManualTask"];

export function attr(node, name) {
	return String(node.get(`spiffworkflow:${name}`) || "").trim();
}

export function isExecutable(node) {
	return Boolean(findParentProcess(node)?.isExecutable);
}

export function isAiAgent(node) {
	return is(node, "bpmn:ServiceTask") && attr(node, "serviceType") === "ai_agent";
}

export function isAiSelector(node) {
	return is(node, "bpmn:AdHocSubProcess") && attr(node, "serviceType") === "ai_task_selector";
}

export function label(node) {
	return node.name || node.id;
}

function descendants(container, found = []) {
	for (const element of container.flowElements || []) {
		found.push(element);
		descendants(element, found);
	}
	return found;
}

function allElements(node) {
	const process = findParentProcess(node);
	return process ? descendants(process) : [];
}

export function adHocSubProcessIds(node) {
	return new Set(
		allElements(node)
			.filter((element) => is(element, "bpmn:AdHocSubProcess"))
			.map((element) => element.id)
	);
}

export function toolBoxIds(node) {
	return new Set(allElements(node).filter(isAiAgent).map((agent) => attr(agent, "aiToolsAdhoc")).filter(Boolean));
}

/** A shape compilation turns into a tool: a human task, or a script/service task that does something. */
export function isToolShape(node) {
	if (HUMAN_TOOL_TYPES.some((type) => is(node, type))) {
		return true;
	}
	return (
		AUTOMATIC_TOOL_TYPES.some((type) => is(node, type)) && Boolean(attr(node, "serverScript") || attr(node, "serviceType"))
	);
}

export function toolShapes(box) {
	return (box.flowElements || []).filter(isToolShape);
}

export function inReferencedToolBox(node) {
	return isToolShape(node) && is(node.$parent, "bpmn:AdHocSubProcess") && toolBoxIds(node).has(node.$parent.id);
}
