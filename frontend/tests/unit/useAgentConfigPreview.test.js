import { beforeEach, describe, expect, it, vi } from "vitest"
import { ref } from "vue"
import { frappeRequest } from "frappe-ui"
import { useAgentConfigPreview } from "../../src/composables/AgentConfig/useAgentConfigPreview.js"

vi.mock("frappe-ui", () => ({ frappeRequest: vi.fn() }))

function context() {
	const ac = {
		props: {
			modelName: "Ticket Triage",
			element: { id: "Agent_1" },
			modeler: { saveXML: vi.fn().mockResolvedValue({ xml: "<bpmn:definitions/>" }) },
		},
		form: ref({ aiSystemPrompt: "Edited", aiModel: "claude-haiku-4-5", aiConversationStore: "custom" }),
	}
	useAgentConfigPreview(ac)
	return ac
}

beforeEach(() => {
	frappeRequest.mockReset()
})

describe("useAgentConfigPreview", () => {
	it("previews the diagram in the editor with the unsaved form values the server reads", async () => {
		frappeRequest.mockResolvedValue({ system_prompt: "Edited", user_prompt: "", tools: [] })
		const ac = context()
		ac.sampleVariables.value = '{"customer": "Acme"}'
		ac.sampleMessage.value = "Hello"

		await ac.loadPreview()

		const { url, params } = frappeRequest.mock.calls[0][0]
		expect(url).toBe("one_bpmn.api.process_maps.preview_ai_task")
		expect(params).toMatchObject({
			model_name: "Ticket Triage",
			bpmn_xml: "<bpmn:definitions/>",
			bpmn_id: "Agent_1",
			sample_variables: '{"customer": "Acme"}',
			sample_message: "Hello",
		})
		const form = JSON.parse(params.form)
		expect(form.aiSystemPrompt).toBe("Edited")
		expect(form).not.toHaveProperty("aiConversationStore")
		expect(ac.preview.value.system_prompt).toBe("Edited")
	})

	it("sends the sample tool results with a dry run", async () => {
		frappeRequest.mockResolvedValue({ output: "Done", error_code: "SUCCESS", turns: [] })
		const ac = context()
		ac.sampleResults.value = '{"lookup": {"ok": true}}'

		await ac.runDryRun()

		const { url, params } = frappeRequest.mock.calls[0][0]
		expect(url).toBe("one_bpmn.api.process_maps.dry_run_ai_task")
		expect(params.sample_results).toBe('{"lookup": {"ok": true}}')
		expect(ac.dryRun.value.output).toBe("Done")
	})

	it("keeps a failed request as an error", async () => {
		frappeRequest.mockRejectedValue(new Error("Not permitted"))
		const ac = context()

		await ac.runDryRun()

		expect(ac.dryRunError.value.message).toBe("Not permitted")
		expect(ac.dryRunLoading.value).toBe(false)
	})
})
