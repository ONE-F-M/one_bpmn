import { describe, expect, it, vi } from "vitest"
import { createSSRApp, h } from "vue"
import { renderToString } from "vue/server-renderer"

vi.mock("frappe-ui", () => {
	const stub = { render: () => h("span") }
	return { ErrorMessage: stub, LoadingIndicator: stub }
})

globalThis.window ??= {}

const { default: PerformanceReportTableDetail } =
	await import("../../src/components/Insights/PerformanceReportTableDetail/PerformanceReportTableDetail.vue")

const ELEMENT = {
	avg_ms: 10800,
	max_ms: 118000,
	avg_steps: 6.4,
	error_runs: 4,
	runs: 212,
	human_wait_runs: 3,
	avg_human_wait_ms: 15120000,
	previous_p95_ms: 22100,
	p95_ms: 31400,
}

const DETAIL = {
	split: { model_share: 41, tool_share: 47, sub_call_share: 12, model_avg_ms: 4400, tool_avg_ms: 5100, sub_call_avg_ms: 1300 },
	steps: [
		{ step_kind: "tool: fetch_contract_pdf", name: "fetch_contract_pdf", via: "", kind: "tool", share: 29, avg_ms: 3100, max_ms: 48000 },
		{ step_kind: "sub-call: risk_review", name: "risk_review", via: "claude-haiku-4-5", kind: "sub_call", share: 12, avg_ms: 1300, max_ms: 6200 },
	],
	runs: [
		{
			name: "run-1",
			started_at: "2026-09-22 14:08:00",
			status: "Error",
			error_code: "TIMEOUT",
			agent_latency_ms: 118000,
			step_count: 14,
			slowest_step: { label: "tool: fetch_contract_pdf", name: "fetch_contract_pdf", latency_ms: 48000 },
		},
	],
	total: 11,
}

function render(props) {
	return renderToString(createSSRApp(PerformanceReportTableDetail, props))
}

describe("the expanded row of the slowest elements table", () => {
	it("lists top steps by bare name with their kind and the model of a sub-call", async () => {
		const html = await render({ element: ELEMENT, detail: DETAIL, remaining: 8, priorDays: 7 })

		expect(html).toContain(">fetch_contract_pdf</span>")
		expect(html).not.toContain(">tool: fetch_contract_pdf</span>")
		expect(html).toContain("via claude-haiku-4-5")
		expect(html).toContain(">Sub-call</td>")
	})

	it("shows each slow run with a status pill, its slowest step and the rest to load", async () => {
		const html = await render({ element: ELEMENT, detail: DETAIL, remaining: 8, priorDays: 7 })

		expect(html).toContain("Error · TIMEOUT")
		expect(html).toContain("fetch_contract_pdf 48.0s")
		expect(html).toContain('href="/processa/runs/run-1"')
		expect(html).toContain("P95 vs prior 7d")
		expect(html).toMatch(/8 more,/)
	})
})
