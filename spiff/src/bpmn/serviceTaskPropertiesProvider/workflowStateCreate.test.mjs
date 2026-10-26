// node --test spiff/src/bpmn/serviceTaskPropertiesProvider/workflowStateCreate.test.mjs

import { test } from "node:test";
import assert from "node:assert/strict";

import { WORKFLOW_STATE_STYLES, createWorkflowState } from "./workflowStateCreate.js";

function recordingPost(outcome) {
	const calls = [];
	const post = (path, body) => {
		calls.push({ path, body });
		return outcome;
	};
	return { post, calls };
}

test("a named state is posted with its style and resolves to the typed name", async () => {
	const { post, calls } = recordingPost(Promise.resolve(undefined));
	const created = await createWorkflowState(post, "  Pending GRD Review ", "Warning");
	assert.equal(created, "Pending GRD Review");
	assert.deepEqual(calls, [
		{ path: "/api/resource/Workflow State", body: { workflow_state_name: "Pending GRD Review", style: "Warning" } },
	]);
});

test("a blank name sends no request", () => {
	const { post, calls } = recordingPost(Promise.resolve(undefined));
	assert.equal(createWorkflowState(post, "   ", "Primary"), null);
	assert.equal(createWorkflowState(post, "", "Primary"), null);
	assert.equal(calls.length, 0);
});

test("the server's error reaches the caller", async () => {
	const { post } = recordingPost(Promise.reject(new Error("Workflow State Pending GRD Review already exists")));
	await assert.rejects(createWorkflowState(post, "Pending GRD Review", "Primary"), /already exists/);
});

test("the style choices are the Workflow State doctype's own", () => {
	assert.deepEqual(WORKFLOW_STATE_STYLES, ["Primary", "Info", "Success", "Warning", "Danger", "Inverse"]);
});
