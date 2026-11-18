import { test } from "vitest"
import assert from "node:assert/strict"

import { BpmnModdle } from "bpmn-moddle"
import traverse from "bpmnlint/lib/traverse.js"

import workflowStateForbiddenDocStatus from "@/bpmn/lint/rules/workflow-state-forbidden-doc-status.js"

const diagram = (body, executable = "true") => `<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
    xmlns:spiffworkflow="http://spiffworkflow.org/bpmn/schema/1.0/core" id="d">
  <bpmn:process id="p" isExecutable="${executable}">${body}</bpmn:process>
</bpmn:definitions>`

const applyWorkflow = (id, status, doctype = "Leave Application") =>
	`<bpmn:serviceTask id="${id}" name="${id}" spiffworkflow:serviceType="apply_workflow" spiffworkflow:serviceTargetDoctype="${doctype}"${status === null ? "" : ` spiffworkflow:docStatus="${status}"`} />`
const userTask = (id) => `<bpmn:userTask id="${id}" name="${id}" />`
const flow = (from, to) => `<bpmn:sequenceFlow id="${from}_${to}" sourceRef="${from}" targetRef="${to}" />`

async function reports(xml) {
	const { rootElement } = await new BpmnModdle().fromXML(xml)
	const { check } = workflowStateForbiddenDocStatus()
	const reported = []
	traverse(rootElement, { enter: (node) => check(node, { report: (id, message) => reported.push({ id, message }) }) })
	return reported
}

const chain = (from, to) => diagram(applyWorkflow("a", from) + applyWorkflow("b", to) + flow("a", "b"))

test("every transition Frappe refuses is reported on the later task", async () => {
	for (const [from, to] of [["0", "2"], ["1", "0"], ["2", "1"], ["2", "0"], ["2", "2"]]) {
		const reported = await reports(chain(from, to))
		assert.equal(reported.length, 1, `${from} to ${to}`)
		assert.equal(reported[0].id, "b")
		assert.match(reported[0].message, /Frappe does not allow/)
	}
})

test("the transitions Frappe allows pass", async () => {
	for (const [from, to] of [["0", "0"], ["0", "1"], ["1", "1"], ["1", "2"]]) {
		assert.deepEqual(await reports(chain(from, to)), [], `${from} to ${to}`)
	}
})

test("a forbidden transition through other shapes and a gateway is reported", async () => {
	const body =
		applyWorkflow("draft", "0") +
		userTask("review") +
		`<bpmn:exclusiveGateway id="gw" />` +
		applyWorkflow("submit", "1") +
		applyWorkflow("cancel", "2") +
		flow("draft", "review") +
		flow("review", "gw") +
		flow("gw", "submit") +
		flow("gw", "cancel")
	const reported = await reports(diagram(body))
	assert.deepEqual(reported.map((report) => report.id), ["cancel"])
	assert.match(reported[0].message, /Draft \(0\) to Cancelled \(2\)/)
})

test("a path from a boundary event is followed", async () => {
	const body =
		applyWorkflow("submit", "1") +
		`<bpmn:boundaryEvent id="timeout" attachedToRef="submit" />` +
		applyWorkflow("draft", "0") +
		flow("timeout", "draft")
	assert.deepEqual((await reports(diagram(body))).map((report) => report.id), ["draft"])
})

test("only the nearest update on the same doctype is compared", async () => {
	const unknownBetween =
		applyWorkflow("a", "0") + applyWorkflow("mid", null) + applyWorkflow("b", "2") + flow("a", "mid") + flow("mid", "b")
	assert.deepEqual(await reports(diagram(unknownBetween)), [])

	const otherDoctype = applyWorkflow("a", "0") + applyWorkflow("b", "2", "Employee") + flow("a", "b")
	assert.deepEqual(await reports(diagram(otherDoctype)), [])
})

test("documentation-only processes are left alone", async () => {
	assert.deepEqual(await reports(diagram(applyWorkflow("a", "0") + applyWorkflow("b", "2") + flow("a", "b"), "false")), [])
})
