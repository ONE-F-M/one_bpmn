import { test } from "vitest"
import assert from "node:assert/strict"

import { missingAiTaskSetting } from "../../src/utils/aiTaskConfig.js"

test("an AI task is configured once it links an agent configuration that has a model", () => {
	assert.equal(missingAiTaskSetting({ aiAgentConfig: "Triage Agent", aiModel: "claude-haiku-4-5" }), null)
})

test("the missing agent configuration is reported before the model", () => {
	assert.equal(missingAiTaskSetting({ aiAgentConfig: "", aiModel: "" }), "agent_config")
	assert.equal(missingAiTaskSetting({ aiAgentConfig: "Triage Agent", aiModel: "  " }), "model")
})

test("a provider and prompt without a linked configuration do not count as configured", () => {
	assert.equal(missingAiTaskSetting({ aiProvider: "Anthropic", aiUserPrompt: "Triage this" }), "agent_config")
})
