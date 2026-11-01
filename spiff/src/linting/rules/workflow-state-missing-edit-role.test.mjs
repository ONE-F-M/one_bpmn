import { test } from "node:test"
import assert from "node:assert/strict"

import { BpmnModdle } from "bpmn-moddle"
import traverse from "bpmnlint/lib/traverse.js"

import workflowStateMissingEditRole from "./workflow-state-missing-edit-role.js"

const diagram = (body, executable = "true") => `<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
    xmlns:spiffworkflow="http://spiffworkflow.org/bpmn/schema/1.0/core" id="d">
  <bpmn:process id="p" isExecutable="${executable}">${body}</bpmn:process>
</bpmn:definitions>`

const task = (type, attrs = "") => `<bpmn:serviceTask id="svc" name="Approve" spiffworkflow:serviceType="${type}" ${attrs} />`

async function reports(xml) {
	const { rootElement } = await new BpmnModdle().fromXML(xml)
	const { check } = workflowStateMissingEditRole()
	const reported = []
	traverse(rootElement, { enter: (node) => check(node, { report: (id, message) => reported.push({ id, message }) }) })
	return reported
}

test("a workflow state update with no Only Allow Edit for role is reported", async () => {
	const reported = await reports(diagram(task("apply_workflow", 'spiffworkflow:workflowState="Approved"')))
	assert.equal(reported.length, 1)
	assert.equal(reported[0].id, "svc")
	assert.match(reported[0].message, /editable role must be defined/)
})

test("a blank Only Allow Edit for role is reported", async () => {
	const reported = await reports(diagram(task("apply_workflow", 'spiffworkflow:onlyAllowEdit="  "')))
	assert.equal(reported.length, 1)
})

test("a workflow state update with a role selected passes", async () => {
	const attrs = 'spiffworkflow:workflowState="Approved" spiffworkflow:onlyAllowEdit="HR Manager"'
	assert.deepEqual(await reports(diagram(task("apply_workflow", attrs))), [])
})

test("other service types and documentation-only processes are left alone", async () => {
	assert.deepEqual(await reports(diagram(task("send_email"))), [])
	assert.deepEqual(await reports(diagram(task("apply_workflow"), "false")), [])
})
