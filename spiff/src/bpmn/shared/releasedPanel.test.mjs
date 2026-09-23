// node --test spiff/src/bpmn/shared/releasedPanel.test.mjs

import { test } from "node:test";
import assert from "node:assert/strict";

import { isConditionUpdate } from "./releasedPanel.js";

test("a conditional start event's condition is a condition update", () => {
	// bpmn-js-spiffworkflow replaces the expression and then announces it as the moddle element.
	const condition = { $type: "bpmn:Expression", body: 'document_type == "SOP"' };
	const bo = {
		$type: "bpmn:StartEvent",
		eventDefinitions: [{ $type: "bpmn:ConditionalEventDefinition", condition }],
	};
	assert.equal(isConditionUpdate(bo, condition), true);
});

test("a sequence flow's condition is a condition update", () => {
	const conditionExpression = { $type: "bpmn:FormalExpression", body: "approved == True" };
	assert.equal(isConditionUpdate({ $type: "bpmn:SequenceFlow", conditionExpression }, conditionExpression), true);
});

test("another nested element on an event is not", () => {
	const timer = { $type: "bpmn:TimerEventDefinition" };
	const bo = { $type: "bpmn:StartEvent", eventDefinitions: [timer] };
	assert.equal(isConditionUpdate(bo, timer), false);
	assert.equal(isConditionUpdate({ $type: "bpmn:StartEvent" }, {}), false);
});
