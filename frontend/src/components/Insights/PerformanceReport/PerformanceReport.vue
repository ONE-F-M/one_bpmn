<template>
	<div class="space-y-6">
		<div class="flex items-center justify-between gap-3">
			<TabButtons
				v-model="groupBy"
				:buttons="GROUP_BY_BUTTONS"
			/>
			<Dropdown
				:options="exportOptions"
				placement="right"
			>
				<Button
					icon-right="chevron-down"
					:disabled="loading || !summary.measured_runs"
				>
					{{ __("Export") }}
				</Button>
			</Dropdown>
		</div>

		<div
			v-if="loading && !reportData.summary"
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
			v-else-if="!summary.runs"
			class="flex flex-col items-center justify-center h-64 text-center"
		>
			<Icon
				icon="lucide:timer"
				class="w-12 h-12 text-gray-400 mb-3"
			/>
			<h3 class="text-base font-medium text-gray-900">{{ __("No runs in this range") }}</h3>
			<p class="text-sm text-gray-500">{{ __("Try a wider date range or different filters") }}</p>
		</div>

		<div
			v-else-if="!summary.measured_runs"
			class="flex flex-col items-center justify-center h-64 text-center"
		>
			<Icon
				icon="lucide:timer-off"
				class="w-12 h-12 text-gray-400 mb-3"
			/>
			<h3 class="text-base font-medium text-gray-900">{{ noTimingText }}</h3>
		</div>

		<template v-else>
			<div class="grid grid-cols-2 sm:grid-cols-3 gap-px bg-gray-200 border border-gray-200 rounded-lg overflow-hidden">
				<MetricTile
					:label="__('P50 agent latency')"
					:value="fmtDuration(summary.p50_ms)"
					:delta="summary.delta_p50_pct"
					good-direction="down"
					:subtitle="measuredSubtitle"
					:subtitle-short="measuredSubtitleShort"
				/>
				<MetricTile
					:label="__('P95 agent latency')"
					:value="fmtDuration(summary.p95_ms)"
					:delta="summary.delta_p95_pct"
					good-direction="down"
					:subtitle="priorDates"
					:subtitle-short="__('vs prior')"
				/>
				<MetricTile
					class="col-span-2 sm:col-span-1"
					:label="__('Time in tools')"
					:value="fmtPct(summary.time_in_tools)"
					:delta="summary.delta_time_in_tools_pt"
					delta-kind="pt"
					good-direction="none"
					:subtitle="splitSubtitle"
				/>
			</div>

			<PerformanceReportChart
				:timeseries="reportData.timeseries || {}"
				:grain="reportData.grain"
				:from-date="reportData.from_date"
				:to-date="reportData.to_date"
			/>

			<PerformanceReportCards
				v-if="isMobile"
				:elements="reportData.elements || []"
				:summary="summary"
				:element-runs="elementRuns"
			/>
			<PerformanceReportTable
				v-else
				:elements="reportData.elements || []"
				:summary="summary"
				:group-by="groupBy"
				:element-runs="elementRuns"
			/>
		</template>
	</div>
</template>

<script setup>
import { ref, computed, watch, onMounted } from "vue"
import {
	Button,
	Dropdown,
	ErrorMessage,
	frappeRequest,
	LoadingIndicator,
	TabButtons,
} from "frappe-ui"
import MetricTile from "@/components/Insights/MetricTile/MetricTile.vue"
import PerformanceReportCards from "@/components/Insights/PerformanceReportCards/PerformanceReportCards.vue"
import PerformanceReportChart from "@/components/Insights/PerformanceReportChart/PerformanceReportChart.vue"
import PerformanceReportTable from "@/components/Insights/PerformanceReportTable/PerformanceReportTable.vue"
import { useElementRuns } from "@/composables/useElementRuns"
import { useWindowSize } from "@/composables/useWindowSize"
import { openReportExport } from "@/utils/exportReport"
import { Icon } from "@iconify/vue"
import {
	fmtDateRange,
	fmtDuration,
	fmtInt as fmtNum,
	fmtPct,
} from "@/utils/formatters"

const props = defineProps({
	fromDate: String,
	toDate: String,
	origin: { type: String, default: "production" },
	model: { type: String, default: "" },
	provider: { type: String, default: "" },
	processModel: { type: String, default: "" },
})

const __ = (window.__ && typeof window.__ === "function") ? window.__ : (s) => s

const GROUP_BY_BUTTONS = [
	{ label: __("By model"), value: "model" },
	{ label: __("By AI agent"), value: "agent" },
]

const loading = ref(false)
const error = ref(null)
const reportData = ref({})
const groupBy = ref("model")

const summary = computed(() => reportData.value.summary || {})

const { isMobile } = useWindowSize()
const elementRuns = useElementRuns(queryParams)

const measuredSubtitle = computed(() => {
	const { runs, measured_runs: measured } = summary.value
	return measured < runs
		? `${fmtNum(measured)} ${__("of")} ${fmtNum(runs)} ${__("runs measured")}`
		: `${__("of")} ${fmtNum(runs)} ${__("runs measured")}`
})
const measuredSubtitleShort = computed(() => {
	const { runs, measured_runs: measured } = summary.value
	return measured < runs ? `${fmtNum(measured)}/${fmtNum(runs)} ${__("runs")}` : `${fmtNum(runs)} ${__("runs")}`
})
const priorDates = computed(() => {
	const { previous_from: from, previous_to: to } = reportData.value
	return `${__("vs")} ${fmtDateRange(from, to)}`
})
const splitSubtitle = computed(() => {
	const s = summary.value
	return [
		`${__("tools")} ${fmtPct(s.tool_share, 0)}`,
		`${__("sub-calls")} ${fmtPct(s.sub_call_share, 0)}`,
		`${__("model")} ${fmtPct(s.model_share, 0)}`,
	].join(" · ")
})
const noTimingText = computed(
	() => `${__("No step timing recorded for")} ${fmtNum(summary.value.runs)} ${__("runs in this range")}`,
)

const exportOptions = computed(() => [
	{ label: "CSV", onClick: () => download("csv") },
	{ label: "XLSX", onClick: () => download("xlsx") },
])

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

function download(fmt) {
	openReportExport("processa.api.insights.export_latency_report", { ...queryParams(), fmt })
}

async function fetchReport() {
	loading.value = true
	error.value = null
	elementRuns.reset()
	try {
		const response = await frappeRequest({
			url: "/api/method/processa.api.insights.get_performance_report",
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
</style>
