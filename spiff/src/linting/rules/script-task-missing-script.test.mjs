import { test } from "node:test"
import assert from "node:assert/strict"

import { BpmnModdle } from "bpmn-moddle"
import traverse from "bpmnlint/lib/traverse.js"

import scriptTaskMissingScript from "./script-task-missing-script.js"

const diagram = (task, executable = "true") => `<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
    xmlns:spiffworkflow="http://spiffworkflow.org/bpmn/schema/1.0/core" id="d">
  <bpmn:process id="p" isExecutable="${executable}">${task}</bpmn:process>
</bpmn:definitions>`

async function reportedIds(xml) {
	const { rootElement } = await new BpmnModdle().fromXML(xml)
	const { check } = scriptTaskMissingScript()
	const reported = []
	traverse(rootElement, { enter: (node) => check(node, { report: (id) => reported.push(id) }) })
	return reported
}

test("a script task with no script is reported", async () => {
	assert.deepEqual(await reportedIds(diagram('<bpmn:scriptTask id="empty" />')), ["empty"])
})

test("a script task with a linked server script is not reported", async () => {
	const task = '<bpmn:scriptTask id="linked" spiffworkflow:serverScript="Notify HR" />'
	assert.deepEqual(await reportedIds(diagram(task)), [])
})

test("a script task with an inline script is not reported", async () => {
	const task = '<bpmn:scriptTask id="inline"><bpmn:script>result["ok"] = True</bpmn:script></bpmn:scriptTask>'
	assert.deepEqual(await reportedIds(diagram(task)), [])
})

test("a script task in a documentation-only process is not reported", async () => {
	assert.deepEqual(await reportedIds(diagram('<bpmn:scriptTask id="doc" />', "false")), [])
})
