import { test } from "vitest";
import assert from "node:assert/strict";
import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

const src = fileURLToPath(new URL("../../src/", import.meta.url));
const read = (file) => readFileSync(join(src, file), "utf8");

const SHELL = "pages/EvalSuite.vue";
const parts = [
	...readdirSync(join(src, "components/Evals"), { recursive: true })
		.filter((f) => f.endsWith(".vue"))
		.map((f) => `components/Evals/${f}`),
	...readdirSync(join(src, "composables"))
		.filter((f) => /^useEval(?!uat)/.test(f) || f === "useAssignableAgents.js")
		.map((f) => `composables/${f}`),
	"utils/evalFormat.js",
	"utils/evalCaseForm.js",
];
const splitFiles = [SHELL, ...parts];
const NEW_PARTS = parts.filter((f) => !/EvalCaseContextField|EvalEarlierConversation/.test(f));

const ENDPOINTS = [
	"one_bpmn.api.eval_api.get_suite_detail",
	"one_bpmn.api.eval_api.list_assignable_agents",
	"one_bpmn.api.eval_api.reassign_suite",
	"one_bpmn.api.eval_api.update_suite_thresholds",
	"one_bpmn.api.eval_api.case_consistency",
	"one_bpmn.api.eval_api.get_eval_case",
	"one_bpmn.api.eval_api.update_eval_case",
	"one_bpmn.api.eval_api.create_eval_case",
	"one_bpmn.agents.eval_runner.run_eval_cases",
	"one_bpmn.agents.eval_runner.run_eval_comparison",
	"one_bpmn.agents.eval_case_factory.list_runs_for_case_picker",
	"one_bpmn.agents.eval_case_factory.get_run_steps_for_case_picker",
	"one_bpmn.agents.eval_case_factory.create_eval_case_from_run",
	"one_bpmn.api.golden_dataset.dataset_readiness",
	"one_bpmn.api.golden_dataset.snapshot_dataset",
	"one_bpmn.api.golden_dataset.import_dataset",
	"one_bpmn.api.golden_dataset.export_dataset",
	"frappe.client.get_list",
];

test("the eval suite page is a shell under 300 lines that calls no endpoint itself", () => {
	const text = read(SHELL);
	assert.ok(text.split("\n").length < 300);
	assert.doesNotMatch(text, /frappeRequest/);
});

test("every Evals component lives in a folder of its own name", () => {
	const dir = join(src, "components/Evals");
	const entries = readdirSync(dir, { withFileTypes: true });
	assert.ok(entries.length > 0);
	for (const entry of entries) {
		assert.ok(entry.isDirectory(), `${entry.name} is loose in components/Evals`);
		assert.deepEqual(
			readdirSync(join(dir, entry.name)).filter((f) => f.endsWith(".vue")),
			[`${entry.name}.vue`],
			entry.name,
		);
	}
});

test("every eval suite part stays under 500 lines", () => {
	for (const file of splitFiles) assert.ok(read(file).split("\n").length < 500, file);
});

test("the split files carry no work-item id, fetch call or localStorage", () => {
	for (const file of splitFiles) {
		const text = read(file);
		assert.doesNotMatch(text, /WI-\d+/, file);
		assert.doesNotMatch(text, /\bfetch\(/, file);
		assert.doesNotMatch(text, /localStorage/, file);
	}
});

test("comments in the new parts use hyphens and no box drawing", () => {
	for (const file of NEW_PARTS) {
		for (const line of read(file).split("\n")) {
			if (/^\s*\/\/|<!--/.test(line))
				assert.doesNotMatch(line, /[\u2014\u2013\u2500-\u257f]/, `${file}: ${line}`);
		}
	}
});

test("the parts call exactly the endpoints the page called before the split", () => {
	const found = new Set();
	for (const file of splitFiles) {
		for (const m of read(file).matchAll(/\/api\/method\/([\w.]+)/g)) found.add(m[1]);
	}
	assert.deepEqual([...found].sort(), [...ENDPOINTS].sort());
});
