import { test, vi } from "vitest";
import assert from "node:assert/strict";
import { ref } from "vue";

vi.mock("frappe-ui", () => ({ frappeRequest: vi.fn().mockResolvedValue({}) }));

const { frappeRequest } = await import("frappe-ui");
const { useProcessDmn } = await import("../../src/composables/useProcessDmn.js");

function makePage(overrides = {}) {
	const fire = vi.fn();
	const pc = {
		activeDiagramName: ref("Model A"),
		showDmnEditorDialog: ref(true),
		dmnEditorTitle: ref(""),
		dmnEditorXml: ref(""),
		dmnEditorKey: ref(0),
		activeDmnElement: { id: "Activity_1", businessObject: { name: "Rule" } },
		activeDmnEventBus: { fire },
		activeDmnDecisionId: "decision_1",
		...overrides,
	};
	useProcessDmn(pc);
	return { pc, fire };
}

test("saving a DMN change writes the decision id back and does not throw", async () => {
	const { pc, fire } = makePage();
	await pc.onDmnXmlChanged("<dmn/>");
	assert.equal(frappeRequest.mock.calls.at(-1)[0].params.decision_id, "decision_1");
	assert.equal(fire.mock.calls.length, 1);
	assert.equal(fire.mock.calls[0][0], "spiff.dmn.edit.update");
	assert.equal(fire.mock.calls[0][1].value, "decision_1");
});

test("without a stored decision id the element id is written back", async () => {
	const { pc, fire } = makePage({ activeDmnDecisionId: null });
	await pc.onDmnXmlChanged("<dmn/>");
	assert.equal(fire.mock.calls[0][1].value, "Activity_1");
});

test("an empty XML change saves nothing and fires nothing", async () => {
	const { pc, fire } = makePage();
	frappeRequest.mockClear();
	await pc.onDmnXmlChanged("");
	assert.equal(frappeRequest.mock.calls.length, 0);
	assert.equal(fire.mock.calls.length, 0);
});
