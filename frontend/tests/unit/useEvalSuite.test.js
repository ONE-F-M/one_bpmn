import { beforeEach, expect, test, vi } from "vitest";

const calls = [];
const responses = {};

vi.mock("frappe-ui", () => ({
	frappeRequest: vi.fn(async ({ url, method, params }) => {
		const name = url.split(".").pop();
		calls.push({ name, method, params });
		const reply = responses[name];
		return typeof reply === "function" ? reply(params) : reply;
	}),
}));

vi.stubGlobal("window", {});
const { createEvalSuiteContext } = await import("@/composables/Eval/useEvalSuiteState.js");

const detail = {
	suite: { agent_configuration: "AG-1" },
	cases: [{ name: "C1" }],
	runs: [],
	total_runs: 2,
	metrics: {},
};
const make = () =>
	createEvalSuiteContext({ params: { suite: "S-1" }, query: {} }, { push: vi.fn() });

beforeEach(() => {
	calls.length = 0;
	for (const key of Object.keys(responses)) delete responses[key];
	responses.get_suite_detail = detail;
	responses.dataset_readiness = { cases: 1 };
	vi.useFakeTimers({ toFake: ["setTimeout"] });
});

test("fetchDetail fills the context and reads the dataset readiness", async () => {
	const ctx = make();
	await ctx.fetchDetail();
	await vi.advanceTimersByTimeAsync(0);
	expect(ctx.cases.value).toHaveLength(1);
	expect(ctx.canRecheck.value).toBe(true);
	expect(calls.map((c) => c.name)).toContain("dataset_readiness");
	expect(ctx.readiness.value).toEqual({ cases: 1 });
});

test("re-check sends the replay backend and adds an optimistic run row", async () => {
	responses.run_eval_cases = "RUN-1";
	const ctx = make();
	await ctx.fetchDetail();
	await ctx.recheckSuite();
	const run = calls.find((c) => c.name === "run_eval_cases");
	expect(run.params.backend).toBe("replay");
	expect(ctx.runs.value[0]).toMatchObject({ name: "RUN-1", status: "Running" });
});

test("a run name already listed is reported as in progress, not added twice", async () => {
	responses.get_suite_detail = { ...detail, runs: [{ name: "RUN-1", status: "Running" }] };
	responses.run_eval_cases = "RUN-1";
	const ctx = make();
	await ctx.fetchDetail();
	await ctx.runWholeSuite();
	expect(ctx.inProgressMessage.value).toMatch(/already in progress/);
	expect(ctx.runs.value).toHaveLength(1);
});

test("saving thresholds sends the gate as 1 or 0 and reloads the suite", async () => {
	responses.update_suite_thresholds = {};
	const ctx = make();
	await ctx.fetchDetail();
	ctx.openThresholds();
	ctx.thresholdForm.gate_deployment = true;
	calls.length = 0;
	await ctx.saveThresholds();
	expect(calls[0].params).toMatchObject({ suite: "S-1", gate_deployment: 1 });
	expect(calls.map((c) => c.name)).toContain("get_suite_detail");
	expect(ctx.showThresholds.value).toBe(false);
});

test("an import is previewed as a dry run before it is applied", async () => {
	responses.import_dataset = ({ dry_run }) => ({
		created: ["a"],
		updated: [],
		left_alone: [],
		merged_from: [],
		skipped: [],
		dry_run,
	});
	const ctx = make();
	await ctx.fetchDetail();
	await ctx.previewImport({ target: { files: [{ name: "f.json", text: async () => "{}" }] } });
	expect(ctx.importPreview.value.dry_run).toBe(1);
	await ctx.applyImport();
	const imports = calls.filter((c) => c.name === "import_dataset");
	expect(imports.map((c) => c.params.dry_run)).toEqual([1, 0]);
	expect(ctx.importPreview.value).toBe(null);
	expect(ctx.datasetMessage.value).toMatch(/Imported 1 new/);
});

test("detaching a suite sends no agent", async () => {
	responses.list_assignable_agents = [];
	responses.reassign_suite = {};
	const ctx = make();
	await ctx.fetchDetail();
	await ctx.openReassign();
	ctx.reassignAgent.value = "";
	await ctx.doReassign();
	expect(calls.find((c) => c.name === "reassign_suite").params.agent_configuration).toBe(null);
	expect(ctx.showReassign.value).toBe(false);
});
