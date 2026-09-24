<template>
	<div class="bg-white rounded-lg shadow-sm p-2 sm:p-4">
		<div
			class="alloc-chart"
			:style="heightStyle"
		>
			<AxisChart :config="config" />
		</div>
	</div>
</template>

<script setup>
import { computed } from "vue"
import { AxisChart } from "frappe-ui"
import { dayjs } from "@/dayjs"
import { fmtCurrency, fmtDateRange } from "@/utils/formatters"
import { bucketTotals, currentBucket, escapeHtml } from "@/utils/costAllocation"

const props = defineProps({
	report: { type: Object, required: true },
	series: { type: Array, required: true },
	colors: { type: Object, required: true },
	groupLabel: { type: String, required: true },
	isPhone: { type: Boolean, default: false },
})

const DAY_MS = 86400000
const BORDER = { borderColor: "#ffffff", borderWidth: 2 }

const heightStyle = computed(() => ({ height: `${props.isPhone ? 170 : 230}px` }))
const buckets = computed(() => props.report.buckets)
const totals = computed(() => bucketTotals(props.series, buckets.value))
const filling = computed(() => currentBucket(buckets.value, props.report.to_date, dayjs().format("YYYY-MM-DD")))

function bucketLabel(bucket) {
	if (props.report.grain === "month") return dayjs(bucket).format("MMM YYYY")
	const next = buckets.value[buckets.value.indexOf(bucket) + 1]
	const end = next ? dayjs(next).subtract(1, "day") : dayjs(props.report.to_date)
	return fmtDateRange(bucket, end.format("YYYY-MM-DD"))
}

function tooltip(params) {
	const points = params.filter((p) => p.value[1])
	if (!points.length) return ""
	const bucket = points[0].value[0]
	const lines = points
		.sort((a, b) => b.value[1] - a.value[1])
		.map((p) => `<div class="flex items-center justify-between gap-5">
			<div class="flex gap-1 items-center">${p.marker}<div>${escapeHtml(p.seriesName)}</div></div>
			<div class="font-bold">${fmtCurrency(p.value[1])}</div></div>`)
	return `<div>${escapeHtml(bucketLabel(bucket))}</div>${lines.join("")}
		<div class="flex items-center justify-between gap-5 border-t mt-1 pt-1">
			<div>Total</div><div class="font-bold">${fmtCurrency(totals.value[bucket])}</div></div>`
}

function totalLabel(p) {
	const total = totals.value[p.value[0]]
	return total ? fmtCurrency(total) : ""
}

function seriesOf(node, i, last) {
	return {
		name: node.label,
		type: "bar",
		stackName: "cost",
		color: props.colors[node.key],
		echartOptions: {
			data: buckets.value.map((b) => ({
				value: [b, node.by_bucket[b]],
				itemStyle: b === filling.value ? { opacity: 0.7 } : {},
			})),
			itemStyle: { ...BORDER, borderRadius: i === last ? [2, 2, 0, 0] : 0 },
			// One label per stack, on its top segment, reading the bucket total.
			label: i === last
				? { show: true, position: "top", fontSize: 11, color: "#4b5563", formatter: totalLabel }
				: { show: false },
		},
	}
}

const config = computed(() => {
	const last = props.series.length - 1
	// A phone fits one legend row, so it scrolls instead of stacking over the plot.
	const legendRows = props.isPhone ? 1 : Math.ceil(props.series.length / 5)
	return {
		data: buckets.value.map((date) => ({ date })),
		title: `${props.report.axis === "chat_user" ? "Chat cost" : "Cost"} by ${props.groupLabel}`,
		subtitle: `${fmtDateRange(props.report.from_date, props.report.to_date)}, ${props.report.grain}ly`,
		xAxis: {
			key: "date",
			type: "time",
			timeGrain: props.report.grain,
			// One tick per bucket; the time axis would otherwise tick every few days.
			echartOptions: { minInterval: (props.report.grain === "month" ? 28 : 7) * DAY_MS },
		},
		yAxis: { title: "Cost (USD)" },
		stacked: true,
		series: props.series.map((node, i) => seriesOf(node, i, last)),
		echartOptions: {
			legend: props.series.length > 1 ? { type: props.isPhone ? "scroll" : "plain", bottom: 0 } : { show: false },
			grid: { bottom: props.series.length > 1 ? 16 + 22 * legendRows : 16, top: 64 },
			tooltip: { formatter: tooltip },
		},
	}
})
</script>

<style scoped></style>
