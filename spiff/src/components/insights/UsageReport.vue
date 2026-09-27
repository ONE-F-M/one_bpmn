<template>
	<div class="space-y-6">
		<div class="flex items-center justify-between gap-3">
			<TabButtons
				v-model="groupBy"
				:buttons="groupByButtons"
			/>
			<Dropdown
				:options="exportOptions"
				placement="right"
			>
				<Button
					icon-right="chevron-down"
					:disabled="loading || !series.length"
				>
					{{ __("Export") }}
				</Button>
			</Dropdown>
		</div>

		<div
			v-if="loading"
			class="flex items-center justify-center h-64"
		>
			<LoadingIndicator class="w-6 h-6 text-gray-500" />
		</div>

		<div
			v-else-if="error"
			class="flex flex-col items-center justify-center h-64 gap-3"
		>
			<ErrorMessage :message="error" />
			<Button
				:label="__('Retry')"
				@click="fetchReport"
			/>
		</div>

		<div
			v-else-if="!series.length"
			class="flex flex-col items-center justify-center h-64 text-center"
		>
			<Icon
				icon="lucide:bar-chart-3"
				class="w-12 h-12 text-gray-400 mb-3"
			/>
			<h3 class="text-base font-medium text-gray-900">{{ __("No runs in this range") }}</h3>
			<p class="text-sm text-gray-500">{{ __("Try a wider date range or different filters") }}</p>
		</div>

		<template v-else>
			<div class="grid grid-cols-1 xl:grid-cols-3 gap-4">
				<div class="xl:col-span-2 bg-white rounded-lg border border-gray-200 p-4">
					<div class="flex items-baseline justify-between gap-3">
						<h3 class="text-sm font-semibold text-gray-900">{{ __("Cost over time") }}</h3>
						<span class="text-xs text-gray-500">{{ chartSubtitle }}</span>
					</div>
					<div class="usage-chart h-[180px] sm:h-[260px]">
						<AxisChart :config="chartConfig" />
					</div>
				</div>
				<div class="bg-white rounded-lg border border-gray-200 p-4">
					<div class="flex items-baseline justify-between gap-3">
						<h3 class="text-sm font-semibold text-gray-900">{{ __("Share of cost") }}</h3>
						<span class="text-xs text-gray-500">{{ fmtCurrency(total.cost) }} {{ __("total") }}</span>
					</div>
					<div class="usage-chart h-[180px] sm:h-[260px]">
						<UsageReportDonut
							:slices="donutSlices"
							:colors="colors"
						/>
					</div>
				</div>
			</div>

			<UsageReportCards
				v-if="isMobile"
				:series="seriesByCost"
				:total="total"
				:colors="colors"
				:prior-label="priorLabel"
			/>
			<UsageReportTable
				v-else
				:series="series"
				:total="total"
				:colors="colors"
				:group-by="groupBy"
			/>
		</template>
	</div>
</template>

<script setup>
import { ref, computed, watch, onMounted } from "vue"
import {
	AxisChart,
	Button,
	Dropdown,
	ErrorMessage,
	frappeRequest,
	LoadingIndicator,
	TabButtons,
} from "frappe-ui"
import { Icon } from "@iconify/vue"
import { dayjs } from "@/dayjs"
import { useWindowSize } from "@/composables/useWindowSize"
import { fmtCurrency } from "@/utils/formatters"
import UsageReportCards from "@/components/insights/UsageReportCards.vue"
import UsageReportDonut from "@/components/insights/UsageReportDonut.vue"
import UsageReportTable from "@/components/insights/UsageReportTable.vue"

const props = defineProps({
	fromDate: { type: String, default: "" },
	toDate: { type: String, default: "" },
	origin: { type: String, default: "production" },
	model: { type: String, default: "" },
	provider: { type: String, default: "" },
	processModel: { type: String, default: "" },
})

const __ = (window.__ && typeof window.__ === "function") ? window.__ : (s) => s
const DONUT_SLICES = 6
const PALETTE = ["#4f46e5", "#0891b2", "#d97706", "#db2777", "#7c3aed", "#059669", "#65a30d", "#ea580c"]
const OTHER_COLOR = "#9ca3af"
const GRAIN_LABELS = {
	day: [__("Daily"), __("days")],
	week: [__("Weekly"), __("weeks")],
	month: [__("Monthly"), __("months")],
}
const TOOLTIP_DATE = {
	day: (d) => dayjs(d).format("MMM D"),
	week: (d) => `${__("Week of")} ${dayjs(d).format("MMM D")}`,
	month: (d) => dayjs(d).format("MMM YYYY"),
}

const groupByButtons = [
	{ label: __("By model"), value: "model" },
	{ label: __("By AI agent"), value: "agent" },
]

const { isMobile } = useWindowSize()
const loading = ref(false)
const error = ref(null)
const reportData = ref({})
const groupBy = ref("model")

const UNATTRIBUTED = __("Unattributed")

const series = computed(() => (reportData.value.series || []).map((s) => ({ ...s, name: s.name || UNATTRIBUTED })))
const total = computed(() => ({ ...(reportData.value.total || {}), delta: reportData.value.delta?.cost ?? null }))
const seriesByCost = computed(() => [...series.value].sort((a, b) => b.cost - a.cost))
const grain = computed(() => reportData.value.grain || "day")
const priorLabel = computed(
	() => `${__("vs prior")} ${dayjs(props.toDate).diff(dayjs(props.fromDate), "day") + 1}d`,
)

// One colour per series name, in cost order, shared by the chart, the donut and the share bars.
const colors = computed(() => {
	const map = { [__("Other")]: OTHER_COLOR }
	for (const s of seriesByCost.value) {
		if (!(s.name in map)) map[s.name] = PALETTE[(Object.keys(map).length - 1) % PALETTE.length]
	}
	return map
})

const chartSubtitle = computed(() => {
	const [grainLabel, unit] = GRAIN_LABELS[grain.value] || GRAIN_LABELS.day
	return `${grainLabel} · ${reportData.value.chart_data?.labels?.length || 0} ${unit}`
})

const chartConfig = computed(() => {
	const { labels = [], datasets = [] } = reportData.value.chart_data || {}
	const ordered = datasets.map((d) => ({ ...d, label: d.label || UNATTRIBUTED })).sort((a, b) => colorRank(a.label) - colorRank(b.label))
	return {
		data: labels.map((date, i) => ({
			date,
			...Object.fromEntries(ordered.map((d) => [d.label, d.values[i]])),
		})),
		colors: ordered.map((d) => colors.value[d.label]),
		xAxis: {
			key: "date",
			type: "time",
			timeGrain: grain.value,
			echartOptions: { axisLabel: { formatter: (v) => dayjs(v).format("MMM D") } },
		},
		yAxis: { echartOptions: { name: "", axisLabel: { formatter: (v) => fmtCurrency(v) } } },
		stacked: true,
		series: ordered.map((d) => ({ name: d.label, type: "bar", color: colors.value[d.label] })),
		echartOptions: { tooltip: { confine: true, formatter: tooltipHtml }, legend: { formatter: (name) => name } },
	}
})

const donutSlices = computed(() => {
	const costByName = {}
	for (const s of seriesByCost.value) costByName[s.name] = (costByName[s.name] || 0) + s.cost
	const slices = Object.entries(costByName)
		.map(([name, cost]) => ({ name, cost }))
		.sort((a, b) => b.cost - a.cost)
	if (slices.length <= DONUT_SLICES) return slices
	const rest = slices.splice(DONUT_SLICES - 1)
	return [...slices, { name: __("Other"), cost: rest.reduce((sum, s) => sum + s.cost, 0) }]
})

const exportOptions = computed(() => [
	{ label: "CSV", onClick: () => download("csv") },
	{ label: "XLSX", onClick: () => download("xlsx") },
])

function colorRank(name) {
	const index = seriesByCost.value.findIndex((s) => s.name === name)
	return index < 0 ? Infinity : index
}

function tooltipHtml(params) {
	const rows = Array.isArray(params) ? params : [params]
	const sum = rows.reduce((acc, p) => acc + (p.value?.[1] || 0), 0)
	const lines = rows.map(
		(p) => `<div class="flex justify-between gap-5"><span>${p.seriesName}</span><span>${fmtCurrency(p.value?.[1])}</span></div>`,
	)
	return [
		`<div class="font-medium mb-1">${TOOLTIP_DATE[grain.value](reportData.value.chart_data?.labels?.[rows[0]?.dataIndex])}</div>`,
		...lines,
		`<div class="flex justify-between gap-5 font-bold border-t mt-1 pt-1"><span>${__("Total")}</span><span>${fmtCurrency(sum)}</span></div>`,
	].join("")
}

function queryParams() {
	return {
		from_date: props.fromDate,
		to_date: props.toDate,
		origin: props.origin,
		model: props.model,
		provider: props.provider,
		process_model: props.processModel,
		group_by: groupBy.value,
	}
}

// The export endpoint replies with a file, so the browser navigates to it instead of fetching.
function download(fmt) {
	const params = new URLSearchParams({ ...queryParams(), fmt })
	window.open(`/api/method/one_bpmn.api.insights_api.export_cost_token_report?${params.toString()}`, "_blank")
}

async function fetchReport() {
	loading.value = true
	error.value = null
	try {
		const response = await frappeRequest({
			url: "/api/method/one_bpmn.api.insights_api.get_cost_token_report",
			method: "POST",
			params: queryParams(),
		})
		reportData.value = response || {}
	} catch (err) {
		error.value = err
		reportData.value = {}
	} finally {
		loading.value = false
	}
}

watch(() => [props.fromDate, props.toDate, props.origin, props.model, props.provider, props.processModel, groupBy.value], fetchReport)
onMounted(fetchReport)
</script>

<style scoped>
.usage-chart :deep(div[class*="min-h-[300px]"]) {
	min-height: 0;
	min-width: 0;
}
</style>
