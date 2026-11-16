import { test } from "vitest";
import assert from "node:assert/strict";

import { existingText, incomingText, overwritePayloads } from "@/utils/configImportDecisions.js";

const items = [
	{ name: "Check Rows", type: "Server Script", incoming_script: "pass" },
	{
		name: "Docu Agent",
		type: "AI Agent Configuration",
		incoming_data: { name: "Docu Agent", enabled: 1 },
	},
	{ name: "Probe Skill", type: "AI Skill", incoming_data: { name: "Probe Skill" } },
];

test("overwritten scripts and agent records go to their own calls", () => {
	const out = overwritePayloads(items, { 0: "overwrite", 1: "overwrite", 2: "skip" });
	assert.deepEqual(out.scripts, [{ name: "Check Rows", script: "pass" }]);
	assert.deepEqual(out.records, [
		{
			doctype: "AI Agent Configuration",
			name: "Docu Agent",
			data: { name: "Docu Agent", enabled: 1 },
		},
	]);
});

test("undecided and skipped rows are left out", () => {
	assert.deepEqual(overwritePayloads(items, {}), { scripts: [], records: [] });
	assert.deepEqual(overwritePayloads(items, { 0: "skip", 1: "skip", 2: "skip" }), {
		scripts: [],
		records: [],
	});
});

test("the diff text comes from the script fields for scripts and the text fields for records", () => {
	assert.equal(existingText({ existing_script: "old" }), "old");
	assert.equal(incomingText({ incoming_script: "new" }), "new");
	assert.equal(existingText({ existing_text: "{}" }), "{}");
	assert.equal(incomingText({}), "");
});
