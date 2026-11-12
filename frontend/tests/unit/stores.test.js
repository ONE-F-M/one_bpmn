import { test, vi } from "vitest";
import assert from "node:assert/strict";

const answers = [];
const calls = [];
vi.mock("frappe-ui", () => ({
	createResource: ({ url }) => ({
		fetch: (params) => {
			calls.push({ url, params });
			return answers.shift();
		},
	}),
}));

const { loadAgentConfigs } = await import("@/stores/agents.js");
const { loadProcessaSettings } = await import("@/stores/settings.js");

test("a store loads once and shares the result", async () => {
	answers.push(Promise.resolve([{ name: "A" }]));
	const first = await loadAgentConfigs();
	const second = await loadAgentConfigs();
	assert.equal(first, second);
	assert.equal(calls.filter((c) => c.url === "frappe.client.get_list").length, 1);
});

test("a permission failure reaches the caller and the next load retries", async () => {
	answers.push(Promise.reject(new Error("No permission for Processa Settings")));
	await assert.rejects(loadProcessaSettings(), /No permission for Processa Settings/);
	answers.push(Promise.resolve({ default_compaction_model: "m" }));
	assert.deepEqual(await loadProcessaSettings(), { default_compaction_model: "m" });
});
