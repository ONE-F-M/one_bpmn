import { test } from "node:test"
import assert from "node:assert/strict"

import { BpmnModdle } from "bpmn-moddle"
import traverse from "bpmnlint/lib/traverse.js"

import sendEmailMissingContent from "./send-email-missing-content.js"
import sendTaskMissingNotification from "./send-task-missing-notification.js"
import serviceTaskMissingConfig from "./service-task-missing-config.js"
import userTaskMissingAssignee from "./user-task-missing-assignee.js"

const diagram = (body, executable = "true") => `<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
    xmlns:spiffworkflow="http://spiffworkflow.org/bpmn/schema/1.0/core" id="d">
  <bpmn:process id="p" isExecutable="${executable}">${body}</bpmn:process>
</bpmn:definitions>`

const service = (type, attrs = "") =>
	`<bpmn:serviceTask id="svc" name="Step" spiffworkflow:serviceType="${type}" ${attrs} />`
const escaped = (json) => json.replaceAll('"', "&quot;")

async function reports(rule, xml) {
	const { rootElement } = await new BpmnModdle().fromXML(xml)
	const { check } = rule()
	const reported = []
	traverse(rootElement, { enter: (node) => check(node, { report: (id, message) => reported.push({ id, message }) }) })
	return reported
}

const problems = async (rule, xml) => (await reports(rule, xml)).map((report) => report.message)

test("apply workflow needs a workflow state or a document status", async () => {
	assert.equal((await problems(serviceTaskMissingConfig, diagram(service("apply_workflow")))).length, 1)
	assert.deepEqual(await problems(serviceTaskMissingConfig, diagram(service("apply_workflow", 'spiffworkflow:workflowState="Approved"'))), [])
	assert.deepEqual(await problems(serviceTaskMissingConfig, diagram(service("apply_workflow", 'spiffworkflow:docStatus="1"'))), [])
})

test("send email and push notification need a recipient", async () => {
	assert.equal((await problems(serviceTaskMissingConfig, diagram(service("send_email")))).length, 1)
	assert.deepEqual(await problems(serviceTaskMissingConfig, diagram(service("send_email", 'spiffworkflow:emailToRoles="HR Manager"'))), [])
	assert.equal((await problems(serviceTaskMissingConfig, diagram(service("push_notification")))).length, 1)
	assert.deepEqual(await problems(serviceTaskMissingConfig, diagram(service("push_notification", 'spiffworkflow:pushToDocFields="owner"'))), [])
})

test("update field needs at least one named field", async () => {
	const rows = (json) => diagram(service("update_field", `spiffworkflow:updateFieldRows="${escaped(json)}"`))
	assert.equal((await problems(serviceTaskMissingConfig, diagram(service("update_field")))).length, 1)
	assert.equal((await problems(serviceTaskMissingConfig, rows("{oops"))).length, 1)
	assert.equal((await problems(serviceTaskMissingConfig, rows('{"field":"status"}'))).length, 1)
	assert.equal((await problems(serviceTaskMissingConfig, rows('[{"field":"","value":"x"}]'))).length, 1)
	assert.deepEqual(await problems(serviceTaskMissingConfig, rows('[{"field":"status","value":"Approved"}]')), [])
	assert.deepEqual(await problems(serviceTaskMissingConfig, diagram(service("update_field", 'spiffworkflow:updateFieldName="status"'))), [])
})

test("google chat needs a type, a message and somewhere to send it", async () => {
	const chat = (attrs) => diagram(service("google_chat", attrs))
	assert.equal((await problems(serviceTaskMissingConfig, chat(""))).length, 1)
	assert.equal((await problems(serviceTaskMissingConfig, chat('spiffworkflow:gchatType="space"'))).length, 2)
	assert.equal((await problems(serviceTaskMissingConfig, chat('spiffworkflow:gchatType="individual" spiffworkflow:gchatMessage="Hi"'))).length, 1)
	const table = 'spiffworkflow:gchatType="individual" spiffworkflow:gchatRecipientBasis="Table Field" spiffworkflow:gchatMessage="Hi"'
	assert.equal((await problems(serviceTaskMissingConfig, chat(table))).length, 1)
	const direct = 'spiffworkflow:gchatType="individual" spiffworkflow:gchatEmail="a@b.com" spiffworkflow:gchatMessage="Hi"'
	assert.deepEqual(await problems(serviceTaskMissingConfig, chat(direct)), [])
	const space = 'spiffworkflow:gchatType="space" spiffworkflow:gchatSpaceId="spaces/X" spiffworkflow:gchatMessage="Hi"'
	assert.deepEqual(await problems(serviceTaskMissingConfig, chat(space)), [])
})

test("a connector needs an id, an operation and object params", async () => {
	const connector = (attrs) => diagram(service("connector", attrs))
	assert.equal((await problems(serviceTaskMissingConfig, connector(""))).length, 2)
	const base = 'spiffworkflow:connectorId="google_drive" spiffworkflow:operation="createFile"'
	assert.deepEqual(await problems(serviceTaskMissingConfig, connector(base)), [])
	assert.equal((await problems(serviceTaskMissingConfig, connector(`${base} spiffworkflow:connectorParams="[]"`))).length, 1)
	assert.equal((await problems(serviceTaskMissingConfig, connector(`${base} spiffworkflow:connectorParams="{oops"`))).length, 1)
})

test("service tasks of other types and documentation-only processes are left alone", async () => {
	assert.deepEqual(await problems(serviceTaskMissingConfig, diagram('<bpmn:serviceTask id="plain" />')), [])
	assert.deepEqual(await problems(serviceTaskMissingConfig, diagram(service("send_email"), "false")), [])
})

test("a send email with no subject or body is warned about", async () => {
	assert.equal((await problems(sendEmailMissingContent, diagram(service("send_email")))).length, 1)
	assert.deepEqual(
		await problems(sendEmailMissingContent, diagram(service("send_email", 'spiffworkflow:emailSubject="Hi" spiffworkflow:emailBody="Body"'))),
		[]
	)
	assert.deepEqual(await problems(sendEmailMissingContent, diagram(service("apply_workflow"))), [])
})

test("a send task with no notification is reported", async () => {
	assert.equal((await problems(sendTaskMissingNotification, diagram('<bpmn:sendTask id="send" />'))).length, 1)
	assert.deepEqual(await problems(sendTaskMissingNotification, diagram('<bpmn:sendTask id="send" spiffworkflow:notificationName="Approved" />')), [])
})

test("a user task needs the value its assignee mode reads", async () => {
	const task = (attrs) => diagram(`<bpmn:userTask id="ut" name="Review" ${attrs} />`)
	assert.deepEqual(await problems(userTaskMissingAssignee, task("")), [])
	assert.deepEqual(await problems(userTaskMissingAssignee, task('spiffworkflow:assigneeMode="User"')), [
		'User Task "Review" assigns by User but its user is empty, so it is left unassigned.',
	])
	assert.match((await problems(userTaskMissingAssignee, task('spiffworkflow:assigneeMode="Round Robin"')))[0], /but its list of users is empty/)
	assert.equal((await problems(userTaskMissingAssignee, task('spiffworkflow:assigneeMode="Round Robin"'))).length, 1)
	assert.equal((await problems(userTaskMissingAssignee, task('spiffworkflow:assigneeMode="Table Field"'))).length, 1)
	assert.deepEqual(await problems(userTaskMissingAssignee, task('spiffworkflow:assigneeMode="User" spiffworkflow:assigneeUser="a@b.com"')), [])
	assert.deepEqual(await problems(userTaskMissingAssignee, task('spiffworkflow:assigneeMode="Load Balancing" spiffworkflow:assigneeUsers="a@b.com,c@d.com"')), [])
})
