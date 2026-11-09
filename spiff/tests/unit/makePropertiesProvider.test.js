import { test } from "vitest";
import assert from "node:assert/strict";

import { makeProvider } from "@/bpmn/shared/makePropertiesProvider.js";

const elementOf = (type) => ({ businessObject: { $instanceOf: (t) => t === type } });
const translate = (text) => `t(${text})`;
const propsFn = ({ element }) => [{ id: "entry", element }];

function register(Provider) {
	const registered = [];
	const panel = {
		registerProvider: (priority, provider) => registered.push({ priority, provider }),
	};
	const provider = new Provider(panel, translate);
	return { registered, provider };
}

test("the class registers itself once at priority 500 and declares what the panel injects", () => {
	const Provider = makeProvider("bpmn:SendTask", "Group", "Label", propsFn);
	const { registered, provider } = register(Provider);
	assert.deepEqual(Provider.$inject, ["propertiesPanel", "translate"]);
	assert.equal(registered.length, 1);
	assert.equal(registered[0].priority, 500);
	assert.equal(registered[0].provider, provider);
});

test("an element of the type gets one group with the id, the translated label and the props entries", () => {
	const { provider } = register(
		makeProvider(
			"bpmn:SendTask",
			"NotificationConfiguration",
			"Notification Configuration",
			propsFn,
		),
	);
	const element = elementOf("bpmn:SendTask");
	const groups = provider.getGroups(element)([]);
	assert.deepEqual(groups, [
		{
			id: "NotificationConfiguration",
			label: "t(Notification Configuration)",
			entries: [{ id: "entry", element }],
		},
	]);
});

test("an element of another type leaves the groups untouched and never asks for entries", () => {
	let asked = false;
	const { provider } = register(
		makeProvider("bpmn:SendTask", "Group", "Label", () => ((asked = true), [])),
	);
	const existing = [{ id: "general" }];
	const groups = provider.getGroups(elementOf("bpmn:UserTask"))(existing);
	assert.equal(groups, existing);
	assert.deepEqual(groups, [{ id: "general" }]);
	assert.equal(asked, false);
});

test("the group goes last by default and first with prepend", () => {
	const element = elementOf("bpmn:Lane");
	const last = register(makeProvider("bpmn:Lane", "New", "Label", propsFn)).provider.getGroups(
		element,
	)([{ id: "general" }]);
	const first = register(
		makeProvider("bpmn:Lane", "New", "Label", propsFn, { prepend: true }),
	).provider.getGroups(element)([{ id: "general" }]);
	assert.deepEqual(
		last.map((g) => g.id),
		["general", "New"],
	);
	assert.deepEqual(
		first.map((g) => g.id),
		["New", "general"],
	);
});

test("a when check that rejects the element leaves the groups untouched even when the type matches", () => {
	const element = elementOf("bpmn:ServiceTask");
	const seen = [];
	const when = (el) => (seen.push(el), false);
	const { provider } = register(
		makeProvider("bpmn:ServiceTask", "Group", "Label", propsFn, { when }),
	);
	assert.deepEqual(provider.getGroups(element)([]), []);
	assert.deepEqual(seen, [element]);
});
