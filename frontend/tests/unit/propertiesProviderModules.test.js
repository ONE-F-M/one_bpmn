import { test, vi } from "vitest";
import assert from "node:assert/strict";

const props = (name) => ({ [name]: ({ element }) => [{ id: name, element }] });
vi.mock("@/bpmn/lanePropertiesProvider/LaneProps", () => props("LaneProps"));
vi.mock("@/bpmn/adhocSubprocessPropertiesProvider/AdhocSubprocessProps", () =>
	props("AdhocSubprocessProps"),
);
vi.mock("@/bpmn/serviceTaskPropertiesProvider/ServiceTaskProps", () => props("ServiceTaskProps"));
vi.mock("@/bpmn/aiAgentPropertiesProvider/AiAgentProps", () => props("AiAgentProps"));
vi.mock("@/bpmn/aiTaskSelectorPropertiesProvider/AiTaskSelectorProps", () =>
	props("AiTaskSelectorProps"),
);
vi.mock("@/bpmn/startEventPropertiesProvider/StartEventProps", () => props("StartEventProps"));
vi.mock("@/bpmn/conditionalStartEventPropertiesProvider/ConditionalStartEventProps", () =>
	props("ConditionalStartEventProps"),
);
vi.mock("@/bpmn/scriptTaskPropertiesProvider/ScriptTaskProps", () => props("ScriptTaskProps"));
vi.mock("@/bpmn/businessRuleTaskPropertiesProvider/BusinessRuleTaskProps", () =>
	props("BusinessRuleTaskProps"),
);
vi.mock("@/bpmn/sendTaskPropertiesProvider/SendTaskProps", () => props("SendTaskProps"));
vi.mock("@/bpmn/userTaskPropertiesProvider/UserTaskProps", () => props("UserTaskProps"));

const SCRIPT_TIP =
	"Link a Frappe Server Script to execute when this task runs. " +
	"The script has access to the full workflow context.";
const RULE_TIP =
	"Link a Frappe-stored DMN decision table to execute when this Business Rule Task runs.";

const MODULES = [
	["lane", "Lane", "bpmn:Lane", "LaneRoleConfiguration", "Lane Role", {}],
	[
		"adhocSubprocess",
		"AdhocSubprocess",
		"bpmn:AdHocSubProcess",
		"AdhocSubprocessConfiguration",
		"Ad-hoc Subprocess",
		{},
	],
	[
		"serviceTask",
		"ServiceTask",
		"bpmn:ServiceTask",
		"ServiceConfiguration",
		"Service Configuration",
		{},
	],
	[
		"aiAgent",
		"AiAgent",
		"bpmn:ServiceTask",
		"AIAgentConfiguration",
		"AI Agent Task",
		{ serviceType: "ai_agent" },
	],
	[
		"aiTaskSelector",
		"AiTaskSelector",
		"bpmn:AdHocSubProcess",
		"AiTaskSelectorConfiguration",
		"AI Task Selector",
		{ serviceType: "ai_task_selector" },
	],
	[
		"startEvent",
		"StartEvent",
		"bpmn:StartEvent",
		"spiffworkflow-trigger-configuration",
		"Trigger Configuration",
		{},
	],
	[
		"conditionalStartEvent",
		"ConditionalStartEvent",
		"bpmn:StartEvent",
		"spiffworkflow-conditional-trigger-configuration",
		"Trigger Configuration",
		{ eventDefinitions: [{ $type: "bpmn:ConditionalEventDefinition" }] },
	],
	[
		"scriptTask",
		"ScriptTask",
		"bpmn:ScriptTask",
		"scriptConfiguration",
		"Script Configuration",
		{ tooltip: SCRIPT_TIP },
	],
	[
		"businessRuleTask",
		"BusinessRuleTask",
		"bpmn:BusinessRuleTask",
		"businessRuleConfiguration",
		"Business Rule Properties",
		{ tooltip: RULE_TIP },
	],
	[
		"sendTask",
		"SendTask",
		"bpmn:SendTask",
		"NotificationConfiguration",
		"Notification Configuration",
		{},
	],
];

const translate = (text) => `t(${text})`;

function element({ type, serviceType, eventDefinitions = [] }) {
	return {
		id: "e1",
		businessObject: {
			$instanceOf: (t) => t === type,
			get: (key) => (key === "spiffworkflow:serviceType" ? serviceType : undefined),
			eventDefinitions,
		},
	};
}

async function load(dir, cap) {
	const mod = await import(`@/bpmn/${dir}PropertiesProvider/${cap}PropertiesProvider.js`);
	return mod.default;
}

function build(Provider) {
	const priorities = [];
	const provider = new Provider({ registerProvider: (p) => priorities.push(p) }, translate);
	return { provider, priorities };
}

const groupIds = (Provider, el) =>
	build(Provider)
		.provider.getGroups(el)([])
		.map((g) => g.id);

for (const [dir, cap, type, groupId, label, extra] of MODULES) {
	test(`${dir}: registers service ${dir}PropertiesProvider as a type with the panel contract`, async () => {
		const module = await load(dir, cap);
		const service = `${dir}PropertiesProvider`;
		assert.deepEqual(Object.keys(module), ["__init__", service]);
		assert.deepEqual(module.__init__, [service]);
		assert.equal(module[service][0], "type");
		const Provider = module[service][1];
		assert.deepEqual(Provider.$inject, ["propertiesPanel", "translate"]);
		assert.deepEqual(build(Provider).priorities, [500]);
	});

	test(`${dir}: its element gets the ${groupId} group, and other elements are left alone`, async () => {
		const Provider = (await load(dir, cap))[`${dir}PropertiesProvider`][1];
		const { provider } = build(Provider);
		const own = element({ type, ...extra });
		const [group] = provider.getGroups(own)([]);
		assert.equal(group.id, groupId);
		assert.equal(group.label, `t(${label})`);
		assert.deepEqual(group.entries, [{ id: `${cap}Props`, element: own }]);
		assert.equal(group.tooltip, extra.tooltip ? `t(${extra.tooltip})` : undefined);
		assert.equal("tooltip" in group, Boolean(extra.tooltip));
		const existing = [{ id: "general" }];
		assert.equal(
			provider.getGroups(element({ type: "bpmn:Participant" }))(existing),
			existing,
		);
		assert.deepEqual(existing, [{ id: "general" }]);
	});
}

test("lane puts its group first, every other group goes last", async () => {
	const lane = (await load("lane", "Lane")).lanePropertiesProvider[1];
	const send = (await load("sendTask", "SendTask")).sendTaskPropertiesProvider[1];
	const seed = () => [{ id: "general" }];
	const laneGroups = build(lane).provider.getGroups(element({ type: "bpmn:Lane" }))(seed());
	const sendGroups = build(send).provider.getGroups(element({ type: "bpmn:SendTask" }))(seed());
	assert.deepEqual(
		laneGroups.map((g) => g.id),
		["LaneRoleConfiguration", "general"],
	);
	assert.deepEqual(
		sendGroups.map((g) => g.id),
		["general", "NotificationConfiguration"],
	);
});

test("a service task shows the generic group unless it is an AI agent, and the AI agent group is the reverse", async () => {
	const service = (await load("serviceTask", "ServiceTask")).serviceTaskPropertiesProvider[1];
	const agent = (await load("aiAgent", "AiAgent")).aiAgentPropertiesProvider[1];
	const plain = element({ type: "bpmn:ServiceTask" });
	const tagged = element({ type: "bpmn:ServiceTask", serviceType: "ai_agent" });
	assert.deepEqual(groupIds(service, plain), ["ServiceConfiguration"]);
	assert.deepEqual(groupIds(service, tagged), []);
	assert.deepEqual(groupIds(agent, plain), []);
	assert.deepEqual(groupIds(agent, tagged), ["AIAgentConfiguration"]);
});

test("the AI task selector group needs the ai_task_selector tag on an ad-hoc subprocess", async () => {
	const selector = (await load("aiTaskSelector", "AiTaskSelector"))
		.aiTaskSelectorPropertiesProvider[1];
	const adhoc = (await load("adhocSubprocess", "AdhocSubprocess"))
		.adhocSubprocessPropertiesProvider[1];
	const plain = element({ type: "bpmn:AdHocSubProcess" });
	const tagged = element({ type: "bpmn:AdHocSubProcess", serviceType: "ai_task_selector" });
	assert.deepEqual(groupIds(selector, plain), []);
	assert.deepEqual(groupIds(selector, tagged), ["AiTaskSelectorConfiguration"]);
	assert.deepEqual(groupIds(adhoc, plain), ["AdhocSubprocessConfiguration"]);
});

test("a plain start event gets the trigger group, a timer start event none, a conditional start event only the conditional group", async () => {
	const start = (await load("startEvent", "StartEvent")).startEventPropertiesProvider[1];
	const conditional = (await load("conditionalStartEvent", "ConditionalStartEvent"))
		.conditionalStartEventPropertiesProvider[1];
	const plain = element({ type: "bpmn:StartEvent" });
	const timer = element({
		type: "bpmn:StartEvent",
		eventDefinitions: [{ $type: "bpmn:TimerEventDefinition" }],
	});
	const cond = element({
		type: "bpmn:StartEvent",
		eventDefinitions: [{ $type: "bpmn:ConditionalEventDefinition" }],
	});
	assert.deepEqual(groupIds(start, plain), ["spiffworkflow-trigger-configuration"]);
	assert.deepEqual(groupIds(start, timer), []);
	assert.deepEqual(groupIds(start, cond), []);
	assert.deepEqual(groupIds(conditional, plain), []);
	assert.deepEqual(groupIds(conditional, timer), []);
	assert.deepEqual(groupIds(conditional, cond), [
		"spiffworkflow-conditional-trigger-configuration",
	]);
});

test("user task is a provider class with the same panel contract", async () => {
	const Provider = await load("userTask", "UserTask");
	assert.deepEqual(Provider.$inject, ["propertiesPanel", "translate"]);
	const { provider, priorities } = build(Provider);
	assert.deepEqual(priorities, [500]);
	const own = element({ type: "bpmn:UserTask" });
	const [group] = provider.getGroups(own)([]);
	assert.equal(group.id, "AssigneeConfiguration");
	assert.equal(group.label, "t(Assignment Configuration)");
	assert.deepEqual(group.entries, [{ id: "UserTaskProps", element: own }]);
	assert.equal("tooltip" in group, false);
	assert.deepEqual(provider.getGroups(element({ type: "bpmn:Lane" }))([]), []);
});
