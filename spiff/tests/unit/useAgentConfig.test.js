import { test, vi } from "vitest";
import assert from "node:assert/strict";
import { readFileSync, readdirSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { join } from "node:path";

vi.stubGlobal("window", {});
vi.mock("frappe-ui", () => ({ frappeRequest: vi.fn().mockResolvedValue({}) }));
vi.mock("vue", async (original) => ({
	...(await original()),
	onMounted: vi.fn(),
	onUnmounted: vi.fn(),
}));

const { frappeRequest } = await import("frappe-ui");
const { createAgentConfigContext } = await import("../../src/composables/useAgentConfigState.js");
const { useAgentConfigStaticContext } =
	await import("../../src/composables/useAgentConfigStaticContext.js");
const { useAgentConfigModels } = await import("../../src/composables/useAgentConfigModels.js");
const { useAgentConfigScreening } =
	await import("../../src/composables/useAgentConfigScreening.js");
const { useAgentConfigLinked } = await import("../../src/composables/useAgentConfigLinked.js");
const { useAgentConfigCreate } = await import("../../src/composables/useAgentConfigCreate.js");
const { useAgentConfigAssistant } =
	await import("../../src/composables/useAgentConfigAssistant.js");
const { useAgentConfigSave } = await import("../../src/composables/useAgentConfigSave.js");

function makeDialog(props = {}) {
	const emit = vi.fn();
	const ac = createAgentConfigContext(
		{ mode: "agent", element: {}, modeler: {}, readonly: false, ...props },
		emit,
	);
	useAgentConfigStaticContext(ac);
	useAgentConfigModels(ac);
	useAgentConfigScreening(ac);
	useAgentConfigLinked(ac);
	useAgentConfigCreate(ac);
	useAgentConfigAssistant(ac);
	useAgentConfigSave(ac);
	return { ac, emit };
}

const CATALOG = [
	{
		name: "m1",
		provider: "p1",
		support_temperature: 1,
		model_name: "M One",
		has_credentials: true,
	},
	{ name: "m2", provider: "p2", support_temperature: 0, has_credentials: false },
	{ name: "m3" },
];

test("the model list narrows to the chosen provider and stays whole without one", () => {
	const { ac } = makeDialog();
	ac.catalogModels.value = CATALOG;
	assert.equal(ac.filteredCatalogModels.value.length, 3);
	ac.form.value.aiProvider = "p1";
	assert.deepEqual(
		ac.filteredCatalogModels.value.map((m) => m.name),
		["m1"],
	);
});

test("choosing a provider clears a model that belongs to another one", () => {
	const { ac } = makeDialog();
	ac.catalogModels.value = CATALOG;
	ac.form.value.aiModel = "m2";
	ac.form.value.aiProvider = "p1";
	ac.onProviderChange();
	assert.equal(ac.form.value.aiModel, "");
	ac.form.value.aiModel = "m1";
	ac.onProviderChange();
	assert.equal(ac.form.value.aiModel, "m1");
});

test("picking a model settles the provider, and sampling follows the model", () => {
	const { ac } = makeDialog();
	ac.catalogModels.value = CATALOG;
	ac.form.value.aiModel = "m2";
	ac.onModelChange();
	assert.equal(ac.form.value.aiProvider, "p2");
	assert.equal(ac.samplingSupported.value, false);
	ac.form.value.aiModel = "m1";
	assert.equal(ac.samplingSupported.value, true);
	ac.form.value.aiModel = "not-listed";
	assert.equal(ac.samplingSupported.value, true);
});

test("model labels say why a model will not work", () => {
	const { ac } = makeDialog();
	ac.catalogModels.value = CATALOG;
	assert.equal(ac.modelLabel(CATALOG[0]), "M One");
	assert.equal(ac.modelLabel(CATALOG[1]), "m2 — no API key");
	assert.equal(ac.modelLabel(CATALOG[2]), "m3 — no provider linked");
	assert.equal(ac.unlistedModelLabel("x"), "x (not in catalog)");
	ac.form.value.aiProvider = "p2";
	assert.equal(ac.unlistedModelLabel("m1"), "M One — not a p2 model");
	assert.equal(ac.unlistedModelLabel("m2"), "");
	ac.siteDefaults.value = { compaction: "fast", distill: "", reconcile: "" };
	assert.equal(ac.inheritLabel("compaction"), "-- Use the site default (fast) --");
	assert.equal(ac.inheritLabel("distill"), "-- Use the default --");
});

test("screening controls group, hide behind an off control, and keep sorted lists", () => {
	const { ac } = makeDialog();
	ac.screeningControls.value = [
		{ fieldname: "a", value: 0, group: "Input" },
		{ fieldname: "b", value: "x", group: "Input", depends_on_field: "a" },
		{ fieldname: "c", value: 1 },
	];
	assert.equal(ac.isOn("a"), false);
	assert.equal(ac.isOn("missing"), true);
	assert.deepEqual(
		ac.controlGroups.value.map((g) => g.name),
		["Input", "Screening"],
	);
	assert.deepEqual(
		ac.visibleIn(ac.controlGroups.value[0]).map((c) => c.fieldname),
		["a"],
	);
	ac.screeningControls.value[0].value = 1;
	assert.equal(ac.visibleIn(ac.controlGroups.value[0]).length, 2);
	const control = { value: ["b"] };
	ac.toggleAllowed(control, "a", true);
	assert.deepEqual(control.value, ["a", "b"]);
	ac.toggleAllowed(control, "b", false);
	assert.deepEqual(control.value, ["a"]);
});

test("a new agent id is scrubbed from its name, and missing fields are refused before any call", async () => {
	const { ac } = makeDialog();
	ac.newAgent.value.agent_name = "  Leave Summarizer! ";
	assert.equal(ac.scrubbedAgentId.value, "leave_summarizer");
	frappeRequest.mockClear();
	await ac.createAgent();
	assert.equal(ac.notice.value.title, "Missing information");
	assert.equal(ac.notice.value.message, "A chat mode label is required.");
	assert.equal(frappeRequest.mock.calls.length, 0);
});

test("config values map onto the form, with flags read as booleans", () => {
	const { ac } = makeDialog();
	assert.equal(ac.configValueToForm("aiCompactionEnabled", 1), true);
	assert.equal(ac.configValueToForm("aiCompactionEnabled", "0"), false);
	assert.equal(ac.configValueToForm("aiLongTermMemory", "Enabled"), true);
	assert.equal(ac.configValueToForm("aiLongTermMemory", "Disabled"), false);
	assert.equal(ac.configValueToForm("aiModel", "m1"), "m1");
	ac.applyConfigFields({ aiModel: "m9", unknownKey: "x", aiTimeout: 5 }, ["aiModel"]);
	assert.equal(ac.form.value.aiModel, "m9");
	assert.equal(ac.form.value.aiTimeout, 30);
	assert.equal("unknownKey" in ac.form.value, false);
});

test("recommended values apply as numbers or text", () => {
	const { ac } = makeDialog();
	ac.applyRecommendation("aiMaxTokens", "2048");
	assert.equal(ac.form.value.aiMaxTokens, 2048);
	ac.applyRecommendation("aiMaxTokens", "lots");
	assert.equal(ac.form.value.aiMaxTokens, 2048);
	ac.applyRecommendation("aiSystemPrompt", 12);
	assert.equal(ac.form.value.aiSystemPrompt, "12");
});

test("the assistant turn context carries the mode and the linked agent", () => {
	const { ac } = makeDialog({ mode: "selector" });
	ac.form.value.aiAgentConfig = "Agent A";
	const dialog = ac.assistantTurnContext.value.assistant_dialog;
	assert.equal(dialog.mode, "selector");
	assert.equal(dialog.linked_config, "Agent A");
	assert.deepEqual(Object.keys(JSON.parse(dialog.current_config)), [
		"aiModel",
		"aiSystemPrompt",
		"aiUserPrompt",
	]);
});

test("saving without a linked agent or a model shows a notice and writes nothing", async () => {
	const { ac, emit } = makeDialog();
	frappeRequest.mockClear();
	await ac.save();
	assert.equal(ac.notice.value.title, "Link an AI Agent Configuration");
	assert.doesNotMatch(ac.notice.value.message, /WI-\d+/);
	ac.form.value.aiAgentConfig = "Agent A";
	await ac.save();
	assert.equal(ac.notice.value.title, "No model set");
	assert.equal(frappeRequest.mock.calls.length, 0);
	assert.equal(emit.mock.calls.length, 0);
});

test("an invalid response schema is refused before the diagram is touched", async () => {
	const { ac, emit } = makeDialog();
	Object.assign(ac.form.value, {
		aiAgentConfig: "Agent A",
		aiModel: "m1",
		aiResponseFormat: "json",
		aiResponseSchema: "{not json",
	});
	await ac.save();
	assert.equal(ac.notice.value.title, "Invalid Response Schema");
	assert.equal(emit.mock.calls.length, 0);
});

test("no work-item id is left in the agent config files", () => {
	const src = fileURLToPath(new URL("../../src/", import.meta.url));
	const files = [
		...readdirSync(join(src, "composables"))
			.filter((f) => /^useAgentConfig(?!LintState)/.test(f))
			.map((f) => `composables/${f}`),
		...readdirSync(join(src, "components/AgentConfig"))
			.filter((f) => f !== "ExampleTrajectory.vue")
			.map((f) => `components/AgentConfig/${f}`),
		"components/Modals/AIAgentConfigModal.vue",
	];
	for (const file of files) {
		assert.doesNotMatch(readFileSync(join(src, file), "utf8"), /WI-\d+/, file);
	}
});
