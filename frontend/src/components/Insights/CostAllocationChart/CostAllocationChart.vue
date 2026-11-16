<template>
	<div class="bg-white rounded-lg border border-gray-200 p-4">
		<div class="flex items-baseline justify-between gap-3">
			<h3 class="text-sm font-semibold text-gray-900">{{ title }}</h3>
			<span class="text-xs text-gray-500">{{ subtitle }}</span>
		</div>
		<div class="alloc-chart h-[250px] sm:h-[260px]">
			<AxisChart :config="config" />
		</div>
	</div>
</template>

<script setup>
import { computed } from "vue"
import { AxisChart } from "frappe-ui"
import { fmtCompact, fmtCurrency, fmtDateRange } from "@/utils/formatters"
import { bucketLabels, bucketTotals, currentBucket, escapeHtml, shortBucketLabels } from "@/utils/costAllocation"
import { dayjs } from "@/dayjs"

const props = defineProps({
	report: { type: Object, required: true },
	series: { type: Array, required: true },
	colors: { type: Object, required: true },
	groupLabel: { type: String, required: true },
	isPhone: { type: Boolean, default: false },
})

const buckets = computed(() => props.report.buckets)
const labels = computed(() => bucketLabels(buckets.value, props.report.to_date, props.report.grain))
const axisLabels = computed(() =>
	props.isPhone ? shortBucketLabels(buckets.value, props.report.to_date, props.report.grain) : labels.value
)
const totals = computed(() => bucketTotals(props.series, buckets.value))
const filling = computed(() => currentBucket(buckets.value, props.report.to_date, dayjs().format("YYYY-MM-DD")))
const title = computed(() => `${props.report.axis === "chat_user" ? "Chat cost" : "Cost"} by ${props.groupLabel}`)
const subtitle = computed(() => `${fmtDateRange(props.report.from_date, props.report.to_date)}, ${props.report.grain}ly`)

function tooltip(params) {
	const points = params.filter((p) => p.value[1])
	if (!points.length) return ""
	const bucket = buckets.value[points[0].dataIndex]
	const lines = points
		.sort((a, b) => b.value[1] - a.value[1])
		.map((p) => `<div class="flex items-center justify-between gap-5">
			<div class="flex gap-1 items-center">${p.marker}<div>${escapeHtml(p.seriesName)}</div></div>
			<div class="font-bold">${fmtCurrency(p.value[1])}</div></div>`)
	return `<div>${escapeHtml(labels.value[points[0].dataIndex])}</div>${lines.join("")}
		<div class="flex items-center justify-between gap-5 border-t mt-1 pt-1">
			<div>Total</div><div class="font-bold">${fmtCurrency(totals.value[bucket])}</div></div>`
}

// "$15" on a whole-dollar tick, "$0.50" when the axis runs in cents.
function axisTick(v) {
	return Number.isInteger(v) ? `$${fmtCompact(v)}` : fmtCurrency(v)
}

function totalLabel(p) {
	const total = totals.value[buckets.value[p.dataIndex]]
	return total ? fmtCurrency(total) : ""
}

function seriesOf(node, i, last) {
	return {
		name: node.label,
		type: "bar",
		stackName: "cost",
		color: props.colors[node.key],
		echartOptions: {
			data: buckets.value.map((b, i) => ({
				value: [labels.value[i], node.by_bucket[b]],
				itemStyle: b === filling.value ? { opacity: 0.7 } : {},
			})),
			barMaxWidth: 160,
			barCategoryGap: "25%",
			itemStyle: { borderRadius: i === last ? [2, 2, 0, 0] : 0 },
			// One label per stack, on its top segment, reading the bucket total.
			label: i === last
				? { show: true, position: "top", fontSize: 11, color: "#4b5563", formatter: totalLabel }
				: { show: false },
		},
	}
}

const config = computed(() => {
	const last = props.series.length - 1
	const legendRows = Math.ceil(props.series.length / (props.isPhone ? 4 : 8))
	return {
		data: labels.value.map((bucket) => ({ bucket })),
		xAxis: {
			key: "bucket",
			type: "category",
			echartOptions: { axisLabel: { interval: 0, fontSize: props.isPhone ? 10 : 12, formatter: (_, i) => axisLabels.value[i] } },
		},
		yAxis: { echartOptions: { name: "", splitLine: { show: false }, axisLabel: { formatter: axisTick } } },
		stacked: true,
		series: props.series.map((node, i) => seriesOf(node, i, last)),
		echartOptions: {
			legend: props.series.length > 1
				? {
					type: "plain",
					left: 0,
					bottom: 0,
					padding: 0,
					itemGap: props.isPhone ? 10 : 16,
					icon: "rect",
					itemWidth: 9,
					itemHeight: 9,
					textStyle: { padding: [0, 0, 0, 1], fontSize: props.isPhone ? 10 : 12 },
				}
				: { show: false },
			grid: { bottom: props.series.length > 1 ? (props.isPhone ? 28 + 18 * legendRows : 10 + 22 * legendRows) : 10, top: 28 },
			tooltip: { confine: true, formatter: tooltip },
		},
	}
})
</script>

<style scoped></style>
