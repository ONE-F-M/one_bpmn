<template>
	<div class="bg-white rounded-lg border border-gray-200 p-4 space-y-3">
		<div class="flex flex-wrap items-baseline justify-between gap-2">
			<h3 class="text-sm font-semibold text-gray-900">{{ __("Agent latency") }}</h3>
			<span class="hidden sm:inline text-xs text-gray-500">{{ subtitle }}</span>
			<span class="sm:hidden text-xs text-gray-500">{{ grainLabel.toLowerCase() }}</span>
		</div>
		<div class="latency-chart h-[150px] sm:h-[220px]">
			<AxisChart :config="chartConfig" />
		</div>
	</div>
</template>

<script setup>
import { computed } from "vue"
import { AxisChart } from "frappe-ui"
import { dayjs } from "@/dayjs"
import { useWindowSize } from "@/composables/useWindowSize"
import { fmtBucketLabel, fmtDateRange, fmtDuration, fmtInt } from "@/utils/formatters"

const props = defineProps({
	timeseries: { type: Object, required: true },
	grain: { type: String, default: "day" },
	fromDate: { type: String, default: "" },
	toDate: { type: String, default: "" },
})

const __ = (window.__ && typeof window.__ === "function") ? window.__ : (s) => s
const P50_COLOR = "#2563eb"
const P95_COLOR = "#d97706"
const P50_KEY = "P50"
const P95_KEY = "P95"
const GRAIN_LABELS = { day: __("Daily"), week: __("Weekly"), month: __("Monthly") }

const { isMobile } = useWindowSize()

const grainLabel = computed(() => GRAIN_LABELS[props.grain] || GRAIN_LABELS.day)
const subtitle = computed(
	() => `${grainLabel.value} · ${fmtDateRange(props.fromDate, props.toDate)} · ${__("agent time, human wait excluded")}`,
)

const chartConfig = computed(() => {
	const { labels = [], p50_ms: p50 = [], p95_ms: p95 = [] } = props.timeseries
	const peak = p95.indexOf(Math.max(...p95.filter((v) => v !== null), 0))
	return {
		data: labels.map((date, i) => ({ date, [P50_KEY]: p50[i], [P95_KEY]: p95[i] })),
		xAxis: {
			key: "date",
			// A time axis adds month-boundary ticks between week buckets; a category axis labels each bucket.
			type: props.grain === "day" ? "time" : "category",
			timeGrain: props.grain,
			echartOptions: { axisLabel: { formatter: dateLabel, hideOverlap: true } },
		},
		yAxis: { echartOptions: { name: "", axisLabel: { formatter: (v) => fmtDuration(v) } } },
		series: [
			{
				name: P50_KEY,
				type: "line",
				color: P50_COLOR,
				showDataPoints: true,
				echartOptions: { connectNulls: false },
			},
			{
				name: P95_KEY,
				type: "line",
				color: P95_COLOR,
				showDataPoints: true,
				echartOptions: {
					connectNulls: false,
					label: {
						show: true,
						position: "top",
						fontSize: 10,
						formatter: (p) => (p.dataIndex === peak && p95[peak] ? fmtDuration(p95[peak]) : ""),
					},
				},
			},
		],
		echartOptions: {
			tooltip: { confine: true, triggerOn: "mousemove|click", formatter: tooltipHtml },
		},
	}
})

function dateLabel(value, index) {
	return isMobile.value && index % 2 ? "" : dayjs(value).format("MMM D")
}

function tooltipHtml(params) {
	const i = params[0].dataIndex
	const { labels = [], p50_ms: p50 = [], p95_ms: p95 = [], runs = [] } = props.timeseries
	const row = (label, value) => `<div class="flex justify-between gap-5"><span>${label}</span><span>${value}</span></div>`
	const duration = (ms) => (ms === null ? __("no timing") : fmtDuration(ms))
	return [
		`<div class="font-medium mb-1">${fmtBucketLabel(labels[i], props.grain)}</div>`,
		row(P50_KEY, duration(p50[i])),
		row(P95_KEY, duration(p95[i])),
		row(__("Measured runs"), fmtInt(runs[i])),
	].join("")
}
</script>

<style scoped>
.latency-chart :deep(div[class*="min-h-[300px]"]) {
	min-height: 0;
	min-width: 0;
}
</style>
