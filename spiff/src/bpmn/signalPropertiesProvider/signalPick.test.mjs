// node --test spiff/src/bpmn/signalPropertiesProvider/signalPick.test.mjs

import { test } from "node:test";
import assert from "node:assert/strict";

import { createBpmnSignalMaster, findOrCreateSignal } from "./signalPick.js";

const moddle = { create: (type, attrs) => ({ $type: type, ...attrs }) };

function diagram(rootElements) {
	const definitions = { rootElements };
	return { event: { $parent: { $parent: definitions } }, definitions };
}

test("a typed name is posted to BPMN Signal Master and resolves to the typed name", async () => {
	const calls = [];
	const post = (path, body) => (calls.push({ path, body }), Promise.resolve());
	assert.equal(await createBpmnSignalMaster(post, "Client Event Decision"), "Client Event Decision");
	assert.deepEqual(calls, [{ path: "/api/resource/BPMN Signal Master", body: { bpmn_signal_name: "Client Event Decision" } }]);
});

test("a server rejection reaches the caller", async () => {
	await assert.rejects(createBpmnSignalMaster(() => Promise.reject(new Error("already exists")), "X"), /already exists/);
});

test("a signal the diagram lacks is added once and reused by the next pick", () => {
	const { event, definitions } = diagram([]);
	const first = findOrCreateSignal(event, moddle, "Client Event Decision");
	const second = findOrCreateSignal(event, moddle, "Client Event Decision");
	assert.equal(first, second);
	assert.equal(definitions.rootElements.length, 1);
	assert.equal(first.name, "Client Event Decision");
	assert.equal(first.$type, "bpmn:Signal");
});

test("an existing signal with the same name is reused, other types are ignored", () => {
	const message = { $type: "bpmn:Message", name: "Client Event Decision" };
	const signal = { $type: "bpmn:Signal", name: "Client Event Decision", id: "Signal_1" };
	const { event, definitions } = diagram([message, signal]);
	assert.equal(findOrCreateSignal(event, moddle, "Client Event Decision"), signal);
	assert.equal(definitions.rootElements.length, 2);
});
