import { beforeEach, describe, expect, it, vi } from "vitest"
import { frappeRequest } from "frappe-ui"
import { useElementRuns } from "../../src/composables/useElementRuns.js"

vi.mock("frappe-ui", () => ({ frappeRequest: vi.fn() }))

const ELEMENT = { key: "task|Model A|claude", p95_ms: 31400 }
const SPLIT = { model_share: 30, tool_share: 50, sub_call_share: 20 }
const method = (call) => call[0].url.split(".").pop()

let filters
let runs

function answer({ url, params }) {
	if (url.endsWith("get_step_latency_report")) return Promise.resolve({ split: SPLIT, rows: [{ step_kind: "tool: a" }] })
	const page = runs.slice(params.offset, params.offset + params.limit)
	return Promise.resolve({ total: runs.length, runs: page })
}

beforeEach(() => {
	filters = { from_date: "2026-11-05", to_date: "2026-11-11", origin: "production", model: "", group_by: "model" }
	runs = Array.from({ length: 11 }, (_, i) => ({ name: `RUN-${i}` }))
	frappeRequest.mockReset()
	frappeRequest.mockImplementation(answer)
})

describe("useElementRuns", () => {
	it("loads the split and the three slowest runs above the element's P95 with the header filters", async () => {
		const elementRuns = useElementRuns(() => filters)

		elementRuns.toggle(ELEMENT)
		await vi.waitFor(() => expect(elementRuns.entry(ELEMENT.key).loading).toBe(false))

		const runsCall = frappeRequest.mock.calls.find((c) => method(c) === "get_element_runs")[0]
		expect(runsCall.params).toMatchObject({ ...filters, key: ELEMENT.key, min_agent_latency_ms: 31400, limit: 3, offset: 0 })
		const stepsCall = frappeRequest.mock.calls.find((c) => method(c) === "get_step_latency_report")[0]
		expect(stepsCall.params).toMatchObject({ ...filters, key: ELEMENT.key, limit: 3 })
		expect(elementRuns.entry(ELEMENT.key).split).toEqual(SPLIT)
		expect(elementRuns.remaining(ELEMENT.key)).toBe(8)
	})

	it("loads ten more runs without refetching the split", async () => {
		const elementRuns = useElementRuns(() => filters)
		elementRuns.toggle(ELEMENT)
		await vi.waitFor(() => expect(elementRuns.entry(ELEMENT.key).loading).toBe(false))

		await elementRuns.load(ELEMENT, true)

		expect(frappeRequest.mock.calls.filter((c) => method(c) === "get_step_latency_report")).toHaveLength(1)
		expect(elementRuns.entry(ELEMENT.key).runs).toHaveLength(11)
		expect(elementRuns.remaining(ELEMENT.key)).toBe(0)
	})

	it("collapses every row and drops cached runs on reset", async () => {
		const elementRuns = useElementRuns(() => filters)
		elementRuns.toggle(ELEMENT)
		await vi.waitFor(() => expect(elementRuns.entry(ELEMENT.key).loading).toBe(false))

		elementRuns.reset()

		expect(elementRuns.isExpanded(ELEMENT.key)).toBe(false)
		expect(elementRuns.entry(ELEMENT.key).runs).toEqual([])
	})

	it("keeps runs from one filter set out of another", async () => {
		const elementRuns = useElementRuns(() => filters)
		elementRuns.toggle(ELEMENT)
		await vi.waitFor(() => expect(elementRuns.entry(ELEMENT.key).loading).toBe(false))

		filters = { ...filters, group_by: "agent" }

		expect(elementRuns.entry(ELEMENT.key).runs).toEqual([])
	})

	it("keeps a failed request in the entry", async () => {
		frappeRequest.mockRejectedValue(new Error("Report failed"))
		const elementRuns = useElementRuns(() => filters)

		elementRuns.toggle(ELEMENT)
		await vi.waitFor(() => expect(elementRuns.entry(ELEMENT.key).loading).toBe(false))

		expect(elementRuns.entry(ELEMENT.key).error.message).toBe("Report failed")
	})
})
