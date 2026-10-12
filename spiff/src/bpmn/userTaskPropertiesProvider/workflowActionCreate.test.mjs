// node --test spiff/src/bpmn/userTaskPropertiesProvider/workflowActionCreate.test.mjs

import { test } from "node:test";
import assert from "node:assert/strict";

import { createWorkflowActionMaster } from "./workflowActionCreate.js";

function recordingPost(outcome) {
	const calls = [];
	const post = (path, body) => {
		calls.push({ path, body });
		return outcome;
	};
	return { post, calls };
}

test("a name is posted and resolves to that name", async () => {
	const { post, calls } = recordingPost(Promise.resolve(undefined));
	const created = await createWorkflowActionMaster(post, "Escalate to GRD");
	assert.equal(created, "Escalate to GRD");
	assert.deepEqual(calls, [
		{ path: "/api/resource/Workflow Action Master", body: { workflow_action_name: "Escalate to GRD" } },
	]);
});

test("the server's error reaches the caller", async () => {
	const { post } = recordingPost(Promise.reject(new Error("Workflow Action Master Escalate to GRD already exists")));
	await assert.rejects(createWorkflowActionMaster(post, "Escalate to GRD"), /already exists/);
});
