import { test } from "vitest";
import assert from "node:assert/strict";

import {
	blankCaseForm,
	caseFormFromServer,
	caseFormPayload,
	caseSaveMessage,
	caseSources,
	incompleteAssertionIndex,
	inputContextError,
	newAssertion,
	newExpectedCall,
} from "@/utils/evalCaseForm.js";

test("a Memory case needs a JSON object with a scope_key", () => {
	const form = { ...blankCaseForm(), case_type: "Memory" };
	assert.match(inputContextError(form, false), /required/);
	assert.match(inputContextError({ ...form, input_context: "{nope" }, false), /not valid JSON/);
	assert.match(inputContextError({ ...form, input_context: "[]" }, false), /JSON object/);
	assert.match(inputContextError({ ...form, input_context: "{}" }, false), /scope_key/);
	assert.equal(inputContextError({ ...form, input_context: '{"scope_key": "x"}' }, false), "");
});

test("a normal case checks its context only when it starts mid conversation", () => {
	const form = blankCaseForm();
	assert.equal(inputContextError(form, false), "");
	assert.match(inputContextError(form, true), /untick Include earlier conversation/);
});

test("the payload sends input context only for Memory or mid-conversation cases", () => {
	const form = { ...blankCaseForm(), title: "t", input_context: "ctx" };
	assert.equal(caseFormPayload(form, false).input_context, "");
	assert.equal(caseFormPayload(form, true).input_context, "ctx");
	assert.equal(caseFormPayload({ ...form, case_type: "Memory" }, false).input_context, "ctx");
	assert.equal(caseFormPayload(form, false).assertions, "[]");
});

test("incompleteAssertionIndex finds the first blank value", () => {
	assert.equal(incompleteAssertionIndex([]), -1);
	assert.equal(incompleteAssertionIndex([{ value: "a" }, { value: "  " }]), 1);
});

test("new expected calls continue the call numbering", () => {
	assert.equal(newExpectedCall([]).call_order, 1);
	assert.equal(newExpectedCall([{ call_order: 1 }, { call_order: 4 }]).call_order, 5);
	assert.equal(newAssertion().pass_threshold, 4);
});

test("server cases get the editor's defaults", () => {
	const form = caseFormFromServer({
		name: "C1",
		title: "T",
		assertions: [{ assertion_type: "contains" }],
		expected_tool_calls: [{ tool_name: "x" }],
	});
	assert.equal(form.case_type, "Output");
	assert.equal(form.assertions[0].pass_threshold, 4);
	assert.equal(form.expected_tool_calls[0].matcher, "equals");
	assert.equal(form.expected_tool_calls[0].call_order, 1);
});

test("case sources link the security event and the run", () => {
	const sources = caseSources({
		source_feedback: "F1",
		source_security_event: "S 1",
		source_run: "R/1",
	});
	assert.equal(sources[0].to, undefined);
	assert.equal(sources[1].to, "/processa/security?event=S%201");
	assert.equal(sources[2].to, "/processa/runs/R%2F1");
});

test("caseSaveMessage unwraps _server_messages and falls back to the message", () => {
	const inner = JSON.stringify({ message: "<b>Title</b> is required" });
	assert.equal(
		caseSaveMessage({ _server_messages: JSON.stringify([inner]) }),
		"Title is required",
	);
	assert.equal(caseSaveMessage({ message: " boom " }), "boom");
});
