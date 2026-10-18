// node --test spiff/src/bpmn/scriptTaskPropertiesProvider/listenForScriptLink.test.mjs

import { test } from "node:test";
import assert from "node:assert/strict";

import EventBus from "diagram-js/lib/core/EventBus.js";

import { listenForScriptLink } from "./listenForScriptLink.js";

const stepA = { id: "Activity_a" };
const stepB = { id: "Activity_b" };

function link(eventBus, element, script, scriptType = "bpmn:script") {
	eventBus.fire("spiff.script.update", { element, scriptType, script });
}

test("a step whose dialog closed without linking keeps its script when another step links one", () => {
	const eventBus = new EventBus();
	const linked = { [stepA.id]: [], [stepB.id]: [] };
	listenForScriptLink(eventBus, stepA, "bpmn:script", (name) => linked[stepA.id].push(name));
	listenForScriptLink(eventBus, stepB, "bpmn:script", (name) => linked[stepB.id].push(name));

	link(eventBus, stepB, "PAM Details is Mandatory");

	assert.deepEqual(linked, { [stepA.id]: [], [stepB.id]: ["PAM Details is Mandatory"] });
});

test("the step still receives its own link later, and only once", () => {
	const eventBus = new EventBus();
	const linked = [];
	listenForScriptLink(eventBus, stepA, "bpmn:script", (name) => linked.push(name));

	link(eventBus, stepB, "Other Step Script");
	link(eventBus, stepA, "GRD Operator Mandatory");
	link(eventBus, stepA, "Later Script");

	assert.deepEqual(linked, ["GRD Operator Mandatory"]);
});

test("a pre-script edited on the same step is not taken as its server script", () => {
	const eventBus = new EventBus();
	const linked = [];
	listenForScriptLink(eventBus, stepA, "bpmn:script", (name) => linked.push(name));

	link(eventBus, stepA, "x = 1", "spiffworkflow:PreScript");

	assert.deepEqual(linked, []);
});
