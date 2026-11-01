import { test } from "node:test"
import assert from "node:assert/strict"

import { BpmnModdle } from "bpmn-moddle"
import traverse from "bpmnlint/lib/traverse.js"

import { storeAgentConfigStates } from "../agentConfigState.js"
import aiTaskConfigIncomplete from "./ai-task-config-incomplete.js"
import aiTaskConfigNotLive from "./ai-task-config-not-live.js"
import aiTaskConfigUnavailable from "./ai-task-config-unavailable.js"

storeAgentConfigStates({
	"Live Bot": { exists: true, enabled: true, lifecycle_status: "Live", problems: [] },
	"Draft Bot": { exists: true, enabled: true, lifecycle_status: "Draft", problems: [] },
	"Off Bot": { exists: true, enabled: false, lifecycle_status: "Live", problems: [] },
	"Gap Bot": { exists: true, enabled: true, lifecycle_status: "Live", problems: ["No AI Model is linked - pick one from the catalog."] },
	"Gone Bot": { exists: false },
})

const diagram = (config, executable = "true") => `<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
    xmlns:spiffworkflow="http://spiffworkflow.org/bpmn/schema/1.0/core" id="d">
  <bpmn:process id="p" isExecutable="${executable}">
    <bpmn:serviceTask id="agent" name="Triage" spiffworkflow:serviceType="ai_agent" spiffworkflow:aiAgentConfig="${config}" />
  </bpmn:process>
</bpmn:definitions>`

async function messages(rule, xml) {
	const { rootElement } = await new BpmnModdle().fromXML(xml)
	const { check } = rule()
	const reported = []
	traverse(rootElement, { enter: (node) => check(node, { report: (id, message) => reported.push(message) }) })
	return reported
}

test("a deleted or disabled configuration is reported", async () => {
	assert.equal((await messages(aiTaskConfigUnavailable, diagram("Gone Bot"))).length, 1)
	assert.equal((await messages(aiTaskConfigUnavailable, diagram("Off Bot"))).length, 1)
	assert.deepEqual(await messages(aiTaskConfigUnavailable, diagram("Live Bot")), [])
})

test("a configuration missing a mandatory setting is reported with the reason", async () => {
	const [message] = await messages(aiTaskConfigIncomplete, diagram("Gap Bot"))
	assert.match(message, /No AI Model is linked/)
	assert.deepEqual(await messages(aiTaskConfigIncomplete, diagram("Live Bot")), [])
})

test("a configuration that is not Live is reported", async () => {
	const [message] = await messages(aiTaskConfigNotLive, diagram("Draft Bot"))
	assert.match(message, /is Draft/)
	assert.deepEqual(await messages(aiTaskConfigNotLive, diagram("Live Bot")), [])
})

test("a disabled or missing configuration is not also reported as not Live", async () => {
	assert.deepEqual(await messages(aiTaskConfigNotLive, diagram("Off Bot")), [])
	assert.deepEqual(await messages(aiTaskConfigNotLive, diagram("Gone Bot")), [])
})

test("a configuration nothing is known about stays quiet", async () => {
	for (const rule of [aiTaskConfigUnavailable, aiTaskConfigIncomplete, aiTaskConfigNotLive]) {
		assert.deepEqual(await messages(rule, diagram("Unknown Bot")), [])
	}
})

test("a documentation-only process is not checked", async () => {
	assert.deepEqual(await messages(aiTaskConfigUnavailable, diagram("Gone Bot", "false")), [])
})
