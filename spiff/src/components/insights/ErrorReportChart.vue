<template>
	<div class="bg-white rounded-lg border border-gray-200 p-4 space-y-3">
		<div class="flex flex-wrap items-baseline justify-between gap-2">
			<h3 class="text-sm font-semibold text-gray-900">{{ __("Error rate over time") }}</h3>
			<span class="text-xs text-gray-500">{{ subtitle }}</span>
		</div>
		<div class="flex flex-wrap gap-2">
			<Button
				v-for="code in codes"
				:key="code.error_code"
				:variant="selectedCode === code.error_code ? 'solid' : 'outline'"
				size="sm"
				@click="$emit('select', selectedCode === code.error_code ? '' : code.error_code)"
			>
				<span class="flex items-center gap-1.5 font-mono text-xs">
					<svg
						viewBox="0 0 8 8"
						class="w-2 h-2"
					>
						<rect
							width="8"
							height="8"
							rx="1"
							:fill="colorFor(code.error_code)"
						/>
					</svg>
					{{ code.error_code }}
					<span class="font-semibold">{{ code.count }}</span>
					<span
						v-if="code.is_new"
						class="rounded-full bg-blue-50 text-blue-700 px-1.5 text-[10px] font-sans"
					>{{ __("new") }}</span>
				</span>
			</Button>
		</div>
		<div class="error-chart h-[150px] sm:h-[220px]">
			<AxisChart :config="chartConfig" />
		</div>
		<p class="text-xs text-gray-500">{{ __("Line: error rate (left axis). Bars: errors by type (right axis).") }}</p>
	</div>
</template>

<script setup>
import { computed } from "vue"
import { AxisChart, Button } from "frappe-ui"
import { dayjs } from "@/dayjs"
import { fmtInt, fmtPct } from "@/utils/formatters"

const props = defineProps({
	timeseries: { type: Object, required: true },
	codes: { type: Array, required: true },
	grain: { type: String, default: "day" },
	fromDate: { type: String, default: "" },
	toDate: { type: String, default: "" },
	selectedCode: { type: String, default: "" },
})

defineEmits(["select"])

const __ = (window.__ && typeof window.__ === "function") ? window.__ : (s) => s
const RATE_KEY = "error_rate"
const UNKNOWN_COLOR = "#9ca3af"
// One colour per code on every visit; codes not listed are grey.
const CODE_COLORS = {
	FAILED_MODEL_CALL: "#c0392b",
	TIMEOUT: "#f5a623",
	TOOL_DENIED: "#4338ca",
	SCHEMA_VALIDATION_FAILED: "#6b7280",
	PROVIDER_DISABLED: "#a3a3a3",
	PROVIDER_NOT_FOUND: "#0d9488",
	TURN_CAP_REACHED: "#9333ea",
	UNEXPECTED_ERROR: "#db2777",
}
const GRAIN_LABELS = { day: __("Daily"), week: __("Weekly"), month: __("Monthly") }

const subtitle = computed(() => {
	const from = dayjs(props.fromDate)
	const to = dayjs(props.toDate)
	const end = from.isSame(to, "month") ? to.format("D") : to.format("MMM D")
	return `${GRAIN_LABELS[props.grain] || GRAIN_LABELS.day} · ${from.format("MMM D")} ${__("to")} ${end} · ${__("click a type to filter the table")}`
})

const chartConfig = computed(() => {
	const { labels = [], error_rate: rates = [], by_code: byCode = [] } = props.timeseries
	const peak = rates.indexOf(Math.max(...rates, 0))
	return {
		data: labels.map((date, i) => ({
			date,
			[RATE_KEY]: rates[i],
			...Object.fromEntries(byCode.map((c) => [c.error_code, c.values[i]])),
		})),
		xAxis: {
			key: "date",
			type: "time",
			timeGrain: props.grain,
			echartOptions: { axisLabel: { formatter: (v) => dayjs(v).format("MMM D") } },
		},
		yAxis: { echartOptions: { name: "", axisLabel: { formatter: (v) => `${v}%` } } },
		y2Axis: { echartOptions: { name: "" } },
		stacked: true,
		series: [
			...byCode.map((c) => ({
				name: c.error_code,
				type: "bar",
				axis: "y2",
				color: colorFor(c.error_code),
				echartOptions: {
					itemStyle: { opacity: props.selectedCode && props.selectedCode !== c.error_code ? 0.3 : 1 },
				},
			})),
			{
				name: RATE_KEY,
				type: "line",
				color: "#111827",
				showDataPoints: true,
				echartOptions: {
					stack: null,
					label: {
						show: true,
						position: "top",
						fontSize: 10,
						formatter: (p) => (p.dataIndex === peak && rates[peak] > 0 ? fmtPct(rates[peak]) : ""),
					},
				},
			},
		],
		echartOptions: {
			legend: { show: false },
			grid: { bottom: 10 },
			tooltip: { confine: true, triggerOn: "mousemove|click", formatter: tooltipHtml },
		},
	}
})

function bucketLabel(date) {
	if (props.grain === "week") return `${__("Week of")} ${dayjs(date).format("MMM D")}`
	if (props.grain === "month") return dayjs(date).format("MMM YYYY")
	return dayjs(date).format("MMM D")
}

function colorFor(code) {
	return CODE_COLORS[code] || UNKNOWN_COLOR
}

function tooltipHtml(params) {
	const rows = Array.isArray(params) ? params : [params]
	const i = rows[0]?.dataIndex ?? 0
	const { labels = [], error_rate: rates = [], runs = [], by_code: byCode = [] } = props.timeseries
	const lines = byCode.map(
		(c) => `<div class="flex justify-between gap-5"><span>${c.error_code}</span><span>${fmtInt(c.values[i])}</span></div>`,
	)
	return [
		`<div class="font-medium mb-1">${bucketLabel(labels[i])}</div>`,
		`<div class="flex justify-between gap-5"><span>${__("Error rate")}</span><span class="font-semibold">${fmtPct(rates[i])}</span></div>`,
		`<div class="flex justify-between gap-5"><span>${__("Counted runs")}</span><span>${fmtInt(runs[i])}</span></div>`,
		...lines,
	].join("")
}
</script>

<style scoped>
.error-chart :deep(div[class*="min-h-[300px]"]) {
	min-height: 0;
	min-width: 0;
}
</style>
