import { test } from "node:test"
import assert from "node:assert/strict"

import { BpmnModdle } from "bpmn-moddle"
import noDisconnected from "bpmnlint/rules/no-disconnected.js"
import noImplicitStart from "bpmnlint/rules/no-implicit-start.js"
import noImplicitEnd from "bpmnlint/rules/no-implicit-end.js"
import traverse from "bpmnlint/lib/traverse.js"

import exemptToolCatalogues from "./tool-catalogue.js"

const diagram = (toolsAdhoc) => `<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
    xmlns:spiffworkflow="http://spiffworkflow.org/bpmn/schema/1.0/core" id="d">
  <bpmn:process id="p" isExecutable="true">
    <bpmn:startEvent id="start"><bpmn:outgoing>f1</bpmn:outgoing></bpmn:startEvent>
    <bpmn:serviceTask id="agent" spiffworkflow:serviceType="ai_agent" spiffworkflow:aiToolsAdhoc="${toolsAdhoc}">
      <bpmn:incoming>f1</bpmn:incoming><bpmn:outgoing>f2</bpmn:outgoing>
    </bpmn:serviceTask>
    <bpmn:endEvent id="end"><bpmn:incoming>f2</bpmn:incoming></bpmn:endEvent>
    <bpmn:adHocSubProcess id="tools"><bpmn:scriptTask id="search" /></bpmn:adHocSubProcess>
    <bpmn:sequenceFlow id="f1" sourceRef="start" targetRef="agent" />
    <bpmn:sequenceFlow id="f2" sourceRef="agent" targetRef="end" />
  </bpmn:process>
</bpmn:definitions>`

async function reportedIds(xml) {
	const { rootElement } = await new BpmnModdle().fromXML(xml)
	const reported = []
	for (const factory of [noDisconnected, noImplicitStart, noImplicitEnd]) {
		const { check } = exemptToolCatalogues(factory)()
		traverse(rootElement, { enter: (node) => check(node, { report: (id) => reported.push(id) }) })
	}
	return reported
}

test("an ad-hoc box an agent names as its tools is not reported", async () => {
	assert.deepEqual(await reportedIds(diagram("tools")), [])
})

test("an ad-hoc box no agent names is still reported", async () => {
	const reported = await reportedIds(diagram("other_tools"))
	assert.deepEqual(reported, ["tools", "tools", "tools"])
})
