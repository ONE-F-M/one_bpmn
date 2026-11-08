import { test, vi } from "vitest";
import assert from "node:assert/strict";

vi.stubGlobal("window", {});
vi.mock("frappe-ui", async () => {
	const { h } = await import("vue");
	return {
		frappeRequest: vi.fn().mockResolvedValue({}),
		Dialog: {
			props: ["modelValue", "options"],
			render: () => h("div", { class: "dialog-stub" }),
		},
	};
});
vi.mock("@iconify/vue", async () => {
	const { h } = await import("vue");
	return {
		Icon: {
			props: ["icon"],
			render() {
				return h("i", { class: this.icon });
			},
		},
	};
});
vi.mock("@/components/Chat/AgentChatPanel.vue", async () => {
	const { h } = await import("vue");
	return { default: { render: () => h("div", { class: "chat-stub" }) } };
});
vi.mock("@/utils/cardRegistry", () => ({ cardRegistry: {} }));
vi.mock("@/composables/useAgentConfigLoad", () => ({
	useAgentConfigLoad: (ac) => {
		for (const [key, value] of Object.entries(globalThis.__agentConfigSeed || {})) {
			if (key === "form") Object.assign(ac.form.value, value);
			else ac[key].value = value;
		}
	},
}));

const { createSSRApp } = await import("vue");
const { renderToString } = await import("vue/server-renderer");
const Modal = (
	await import("../../src/components/Modals/AIAgentConfigModal/AIAgentConfigModal.vue")
).default;

const LINKED = {
	form: {
		aiAgentConfig: "Agent A",
		aiModel: "m1",
		aiLongTermMemory: true,
		aiMemoryWriteMode: "distilled",
		aiCompactionEnabled: true,
		aiAgentRoles: [{ role: "Held Role" }],
		aiExamples: [
			{
				input: "in",
				context_summary: "",
				trajectory: null,
				expected_output: "",
				note: "",
				enabled: 1,
			},
		],
		aiGuardrails: [{ guardrail: "no secrets", category: "Safety", enabled: 1 }],
	},
	catalogModels: [{ name: "m1", provider: "p1", support_temperature: 1 }],
	agentConfigs: [{ name: "Agent A", agent_id: "a" }],
	linkedAgentStatus: "Needs Attention",
	screeningControls: [{ fieldname: "pii", label: "PII", value: 1, group: "Input Screening" }],
};

async function render(props = {}, seed = {}) {
	const warnings = [];
	globalThis.__agentConfigSeed = seed;
	const app = createSSRApp(Modal, {
		element: {},
		modeler: {},
		mode: "agent",
		readonly: false,
		...props,
	});
	app.config.warnHandler = (message) => warnings.push(message);
	const html = await renderToString(app);
	return { html, warnings };
}

test("a fresh agent dialog renders the form, the assistant panel and no warnings", async () => {
	const { html, warnings } = await render();
	assert.deepEqual(warnings, []);
	assert.match(html, /Configure AI Agent Task/);
	for (const text of ["Advanced Settings", "Memory", "Golden Dataset", "Output Variable Name"]) {
		assert.ok(html.includes(text), text);
	}
	assert.match(html, /class="assistant-panel"/);
	assert.match(html, /class="btn-save"/);
	assert.doesNotMatch(html, /Re-run checks/);
});

test("a linked agent shows its status, static context, permissions and screening", async () => {
	const { html, warnings } = await render({}, LINKED);
	assert.deepEqual(warnings, []);
	for (const text of [
		"Re-run checks",
		"Needs Attention",
		"Example 1",
		"no secrets",
		"Held Role",
		"Input Screening",
	]) {
		assert.ok(html.includes(text), text);
	}
});

test("the selector dialog hides the fields the selector never reads", async () => {
	const { html, warnings } = await render({ mode: "selector" }, LINKED);
	assert.deepEqual(warnings, []);
	assert.match(html, /Configure AI Task Selector/);
	for (const text of [
		"Output Variable Name",
		"Response Format",
		"Max Retries",
		"Golden Dataset",
	]) {
		assert.ok(!html.includes(text), text);
	}
});

test("a read-only dialog disables the form and drops Save and the assistant", async () => {
	const { html, warnings } = await render({ readonly: true }, LINKED);
	assert.deepEqual(warnings, []);
	assert.match(html, /View only/);
	assert.match(html, /<fieldset class="field-gate"[^>]*disabled/);
	assert.doesNotMatch(html, /class="btn-save"/);
	assert.doesNotMatch(html, /class="assistant-panel"/);
});

test("the create panel opens with its fields", async () => {
	const { html, warnings } = await render(
		{},
		{ showCreateAgent: true, catalogModels: LINKED.catalogModels },
	);
	assert.deepEqual(warnings, []);
	for (const text of [
		"New AI Agent Configuration",
		"Agent Name",
		"Sample Prompts",
		"Create agent",
	]) {
		assert.ok(html.includes(text), text);
	}
});
