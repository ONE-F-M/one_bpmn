import { test } from "node:test"
import assert from "node:assert/strict"

import { NOTIFY_EDITOR_ATTRS, contextDoctype, isHtmlMode } from "./notifyAssigneeAttrs.js"

const startEvent = (attrs = {}, eventDefinitions = []) => ({ $type: "bpmn:StartEvent", $attrs: attrs, eventDefinitions })
const userTask = (process, attrs = {}) => ({ $type: "bpmn:UserTask", $parent: process, $attrs: attrs })

test("NOTIFY_EDITOR_ATTRS: lists every editor attribute once", () => {
	assert.equal(new Set(NOTIFY_EDITOR_ATTRS).size, NOTIFY_EDITOR_ATTRS.length)
	for (const name of ["notifyLayout", "notifySubjectAr", "notifyQuestionEn", "notifyQuestionAr", "notifyFacts",
		"notifyDetails", "notifyAttachments", "notifyActions", "notifyConversation", "notifyTokenHours", "notifyArabicEdited"]) {
		assert.ok(NOTIFY_EDITOR_ATTRS.includes(name), name)
	}
})

test("isHtmlMode: no layout, html, or an unknown value send today's email", () => {
	for (const value of [undefined, "", "html", "other"]) assert.equal(isHtmlMode(value), true, String(value))
})

test("isHtmlMode: a picked layout is layout mode", () => {
	for (const value of ["card", "steps", "chat"]) assert.equal(isHtmlMode(value), false, value)
})

test("contextDoctype: the start event trigger wins over the task target", () => {
	const process = { $type: "bpmn:Process", flowElements: [startEvent({ "spiffworkflow:triggerDoctype": "Leave Application" })] }
	assert.equal(contextDoctype(userTask(process, { "spiffworkflow:targetDoctype": "Employee" })), "Leave Application")
})

test("contextDoctype: a trigger on the conditional event definition counts", () => {
	const process = { $type: "bpmn:Process", flowElements: [startEvent({}, [{ $attrs: { "spiffworkflow:triggerDoctype": "HD Ticket" } }])] }
	assert.equal(contextDoctype(userTask(process)), "HD Ticket")
})

test("contextDoctype: falls back to the task target, through a sub-process", () => {
	const process = { $type: "bpmn:Process", flowElements: [startEvent()] }
	const sub = { $type: "bpmn:SubProcess", $parent: process }
	assert.equal(contextDoctype(userTask(sub, { "spiffworkflow:targetDoctype": "Employee" })), "Employee")
})

test("contextDoctype: empty when neither is set", () => {
	assert.equal(contextDoctype(userTask({ $type: "bpmn:Process", flowElements: [] })), "")
})
