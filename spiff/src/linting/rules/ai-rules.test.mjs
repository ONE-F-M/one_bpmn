import { test } from "node:test"
import assert from "node:assert/strict"

import { BpmnModdle } from "bpmn-moddle"
import traverse from "bpmnlint/lib/traverse.js"

import aiTaskInvalidSettings from "./ai-task-invalid-settings.js"
import aiTaskMissingConfig from "./ai-task-missing-config.js"
import aiTaskMissingUserPrompt from "./ai-task-missing-user-prompt.js"
import aiToolMissingDescription from "./ai-tool-missing-description.js"
import aiToolParamsInvalidJson from "./ai-tool-params-invalid-json.js"
import aiToolsBoxNotFound from "./ai-tools-box-not-found.js"
import aiToolsBoxUnreferenced from "./ai-tools-box-unreferenced.js"

const diagram = (body, executable = "true") => `<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
    xmlns:spiffworkflow="http://spiffworkflow.org/bpmn/schema/1.0/core" id="d">
  <bpmn:process id="p" isExecutable="${executable}">${body}</bpmn:process>
</bpmn:definitions>`

const agent = (attrs = "") =>
	`<bpmn:serviceTask id="agent" name="Triage" spiffworkflow:serviceType="ai_agent" ${attrs} />`
const box = (inner, attrs = "") => `<bpmn:adHocSubProcess id="box" name="Tools" ${attrs}>${inner}</bpmn:adHocSubProcess>`
const tool = (attrs = "", inner = "") =>
	`<bpmn:scriptTask id="tool" name="Lookup" spiffworkflow:serverScript="Find" ${attrs}>${inner}</bpmn:scriptTask>`
const escaped = (json) => json.replaceAll('"', "&quot;")

async function reports(rule, xml) {
	const { rootElement } = await new BpmnModdle().fromXML(xml)
	const { check } = rule()
	const reported = []
	traverse(rootElement, { enter: (node) => check(node, { report: (id, message) => reported.push({ id, message }) }) })
	return reported
}

const ids = async (rule, xml) => (await reports(rule, xml)).map((report) => report.id)

test("an AI agent with no configuration is reported, one with a configuration is not", async () => {
	assert.deepEqual(await ids(aiTaskMissingConfig, diagram(agent())), ["agent"])
	assert.deepEqual(await ids(aiTaskMissingConfig, diagram(agent('spiffworkflow:aiAgentConfig="Triage Bot"'))), [])
})

test("an AI task selector with no configuration is reported", async () => {
	const selector = '<bpmn:adHocSubProcess id="pick" spiffworkflow:serviceType="ai_task_selector" />'
	assert.deepEqual(await ids(aiTaskMissingConfig, diagram(selector)), ["pick"])
})

test("AI shapes in a documentation-only process are not reported", async () => {
	assert.deepEqual(await ids(aiTaskMissingConfig, diagram(agent(), "false")), [])
})

test("an AI agent with no user prompt is reported", async () => {
	assert.deepEqual(await ids(aiTaskMissingUserPrompt, diagram(agent())), ["agent"])
	assert.deepEqual(await ids(aiTaskMissingUserPrompt, diagram(agent('spiffworkflow:aiUserPrompt="{{ ticket }}"'))), [])
})

test("a Tools box that does not exist is reported", async () => {
	const missing = agent('spiffworkflow:aiToolsAdhoc="Gone"') + box(tool())
	assert.deepEqual(await ids(aiToolsBoxNotFound, diagram(missing)), ["agent"])
	const found = agent('spiffworkflow:aiToolsAdhoc="box"') + box(tool())
	assert.deepEqual(await ids(aiToolsBoxNotFound, diagram(found)), [])
})

test("a tool with no documentation is warned about by name", async () => {
	const xml = diagram(agent('spiffworkflow:aiToolsAdhoc="box"') + box(tool()))
	assert.deepEqual(await reports(aiToolMissingDescription, xml), [
		{ id: "tool", message: "Tool 'Lookup' has no description; the model will see only its id" },
	])
})

test("a documented tool, or one outside a Tools box, is not warned about", async () => {
	const documented = tool("", "<bpmn:documentation>Finds a ticket by id.</bpmn:documentation>")
	assert.deepEqual(
		await ids(aiToolMissingDescription, diagram(agent('spiffworkflow:aiToolsAdhoc="box"') + box(documented))),
		[]
	)
	assert.deepEqual(await ids(aiToolMissingDescription, diagram(box(tool()))), [])
})

test("tool parameters that are not a valid schema are reported", async () => {
	const withParams = (json) =>
		diagram(agent('spiffworkflow:aiToolsAdhoc="box"') + box(tool(`spiffworkflow:aiToolParams="${escaped(json)}"`)))
	assert.deepEqual(await ids(aiToolParamsInvalidJson, withParams("{not json")), ["tool"])
	assert.deepEqual(await ids(aiToolParamsInvalidJson, withParams("[]")), ["tool"])
	assert.deepEqual(await ids(aiToolParamsInvalidJson, withParams('{"properties":{"id":{}},"required":["name"]}')), ["tool"])
	assert.deepEqual(await ids(aiToolParamsInvalidJson, withParams('{"properties":{"id":{}},"required":["id"]}')), [])
})

test("a Tools box no agent uses is reported, a used one and a selector are not", async () => {
	assert.deepEqual(await ids(aiToolsBoxUnreferenced, diagram(box(tool()))), ["box"])
	assert.deepEqual(await ids(aiToolsBoxUnreferenced, diagram(agent('spiffworkflow:aiToolsAdhoc="box"') + box(tool()))), [])
	const selector = box(tool(), 'spiffworkflow:serviceType="ai_task_selector"')
	assert.deepEqual(await ids(aiToolsBoxUnreferenced, diagram(selector)), [])
})

test("a raw API key, a bad Max Tokens and a broken response schema are each reported", async () => {
	const settings = async (attrs) => (await reports(aiTaskInvalidSettings, diagram(agent(attrs)))).length
	assert.equal(await settings('spiffworkflow:aiApiKey="anything"'), 1)
	assert.equal(await settings('spiffworkflow:aiSystemPrompt="sk-abc123"'), 1)
	assert.equal(await settings('spiffworkflow:aiMaxTokens="0"'), 1)
	assert.equal(await settings('spiffworkflow:aiMaxTokens="lots"'), 1)
	assert.equal(await settings('spiffworkflow:aiResponseFormat="json" spiffworkflow:aiResponseSchema="{oops"'), 1)
	assert.equal(await settings('spiffworkflow:aiMaxTokens="2048"'), 0)
	assert.equal(await settings('spiffworkflow:aiResponseFormat="json" spiffworkflow:aiResponseSchema="{}"'), 0)
})
