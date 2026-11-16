import { test } from "vitest"
import assert from "node:assert/strict"

import { openReportExport } from "../../src/utils/exportReport.js"

test("openReportExport opens the method with every filter and the format", () => {
	const opened = []
	globalThis.window = { open: (url, target) => opened.push([url, target]) }

	openReportExport("processa.api.insights.export_latency_report", { from_date: "2026-11-05", group_by: "agent", fmt: "xlsx" })

	assert.deepEqual(opened, [
		[
			"/api/method/processa.api.insights.export_latency_report?from_date=2026-11-05&group_by=agent&fmt=xlsx",
			"_blank",
		],
	])
})
