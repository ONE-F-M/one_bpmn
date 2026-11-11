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

			<!-- Main Table -->
			<div
				v-if="reportData.rows?.length"
				class="overflow-x-auto"
			>
				<table class="w-full">
					<thead>
						<tr class="border-b border-gray-200">
							<th class="text-left text-xs uppercase text-gray-500 font-medium py-2 px-3 w-8"></th>
							<th class="text-left text-xs uppercase text-gray-500 font-medium py-2 px-3">{{ groupBy === "agent" ? "AI Agent" : "Model" }}</th>
							<th class="text-left text-xs uppercase text-gray-500 font-medium py-2 px-3">BPMN Element</th>
							<th class="text-right text-xs uppercase text-gray-500 font-medium py-2 px-3">Runs</th>
							<th class="text-right text-xs uppercase text-gray-500 font-medium py-2 px-3">Avg</th>
							<th class="text-right text-xs uppercase text-gray-500 font-medium py-2 px-3">p50</th>
							<th class="text-right text-xs uppercase text-gray-500 font-medium py-2 px-3">p95</th>
							<th class="text-right text-xs uppercase text-gray-500 font-medium py-2 px-3">Max</th>
							<th class="text-right text-xs uppercase text-gray-500 font-medium py-2 px-3">Avg Steps</th>
							<th class="text-right text-xs uppercase text-gray-500 font-medium py-2 px-3">Avg Tokens</th>
						</tr>
					</thead>
					<tbody>
						<template v-for="(row, idx) in reportData.rows" :key="idx">
							<tr
								class="border-b border-gray-100 hover:bg-gray-50 transition-colors cursor-pointer"
								@click="toggleExpand(idx)"
							>
								<td class="py-3 px-3">
									<Icon
										:icon="expandedRow === idx ? 'lucide:chevron-down' : 'lucide:chevron-right'"
										class="w-4 h-4 text-gray-400"
									/>
								</td>
								<td class="py-3 px-3 text-sm text-gray-900 font-medium">{{ row.model }}</td>
								<td class="py-3 px-3 text-sm text-gray-600">{{ row.bpmn_label || row.bpmn_id || "—" }}</td>
								<td class="py-3 px-3 text-sm text-gray-600 text-right">{{ fmtNum(row.runs) }}</td>
								<td class="py-3 px-3 text-sm text-gray-600 text-right">{{ fmtDuration(row.avg_duration_ms) }}</td>
								<td class="py-3 px-3 text-sm text-gray-600 text-right">{{ fmtDuration(row.p50_duration_ms) }}</td>
								<td class="py-3 px-3 text-sm text-right font-medium" :class="row.p95_duration_ms > 5000 ? 'text-red-600' : 'text-gray-600'">
									{{ fmtDuration(row.p95_duration_ms) }}
								</td>
								<td class="py-3 px-3 text-sm text-gray-600 text-right">{{ fmtDuration(row.max_duration_ms) }}</td>
								<td class="py-3 px-3 text-sm text-gray-600 text-right">{{ row.avg_steps }}</td>
								<td
									class="py-3 px-3 text-sm text-gray-600 text-right"
									:title="fmtNum(row.avg_tokens)"
								>
									{{ fmtCompact(row.avg_tokens) }}
								</td>
							</tr>

							<!-- Expanded: Recent runs -->
							<tr v-if="expandedRow === idx">
								<td colspan="10" class="bg-gray-50 p-4">
									<div v-if="recentRunsLoading" class="flex items-center justify-center py-6">
										<div class="text-gray-500 text-sm">Loading recent runs...</div>
									</div>
									<div
										v-else-if="recentRunsError"
										class="flex justify-center py-6"
									>
										<ErrorMessage :message="recentRunsError" />
									</div>
									<div v-else-if="recentRuns.length === 0" class="flex items-center justify-center py-6">
										<div class="text-gray-400 text-sm">No recent runs found</div>
									</div>
									<table v-else class="w-full">
										<thead>
											<tr class="border-b border-gray-200">
												<th class="text-left text-xs uppercase text-gray-500 font-medium py-1.5 px-2 w-8"></th>
												<th class="text-left text-xs uppercase text-gray-500 font-medium py-1.5 px-2">Run</th>
												<th class="text-left text-xs uppercase text-gray-500 font-medium py-1.5 px-2">Status</th>
												<th class="text-right text-xs uppercase text-gray-500 font-medium py-1.5 px-2">Duration</th>
												<th class="text-right text-xs uppercase text-gray-500 font-medium py-1.5 px-2">Tokens</th>
												<th class="text-right text-xs uppercase text-gray-500 font-medium py-1.5 px-2">Cost</th>
												<th class="text-right text-xs uppercase text-gray-500 font-medium py-1.5 px-2">Sub-runs</th>
												<th class="text-left text-xs uppercase text-gray-500 font-medium py-1.5 px-2">Started</th>
											</tr>
										</thead>
										<tbody>
											<template v-for="(run, ri) in recentRuns" :key="run.name">
												<tr
													class="border-b border-gray-100 hover:bg-white transition-colors cursor-pointer"
													@click="toggleSteps(ri, run.name)"
												>
													<td class="py-2 px-2">
														<Icon
															:icon="expandedStepRun === ri ? 'lucide:chevron-down' : 'lucide:chevron-right'"
															class="w-3 h-3 text-gray-400"
														/>
													</td>
													<td class="py-2 px-2 text-xs font-mono">
														<router-link :to="`/processa/runs/${run.name}`" class="text-blue-600 hover:underline" title="Open the full run" @click.stop>{{ run.name }}</router-link>
													</td>
													<td class="py-2 px-2">
														<Badge :theme="run.status === 'Success' ? 'green' : 'red'" size="sm">{{ run.status }}</Badge>
													</td>
													<td class="py-2 px-2 text-xs text-gray-600 text-right">{{ fmtDuration(run.duration_ms) }}</td>
													<!-- The turn's total, sub-runs included; the run's own figure on hover -->
													<td
														class="py-2 px-2 text-xs text-gray-600 text-right"
														:title="runTokensTitle(run)"
													>
														{{ fmtCompact(run.tree_total_tokens ?? run.total_tokens) }}
													</td>
													<td
														class="py-2 px-2 text-xs text-gray-600 text-right"
														:title="runCostTitle(run)"
													>
														{{ fmtCurrency(run.tree_estimated_cost ?? run.estimated_cost) }}
													</td>
													<td class="py-2 px-2 text-xs text-gray-600 text-right">{{ run.child_runs || "—" }}</td>
													<td class="py-2 px-2 text-xs text-gray-500">{{ formatDate(run.started_at) }}</td>
												</tr>

												<!-- Steps detail: the run as a tree -->
												<tr v-if="expandedStepRun === ri && (tree || treeError)">
													<td colspan="8" class="bg-white p-3">
														<ErrorMessage
															v-if="treeError"
															:message="treeError"
														/>
														<RunTree
															v-else
															:node="tree"
														/>
													</td>
												</tr>
											</template>
										</tbody>
									</table>
								</td>
							</tr>
						</template>
					</tbody>
				</table>
			</div>
		</template>
	</div>
</template>

<script setup>
import { ref, computed, watch, onMounted } from "vue"
import {
	Badge,
	Button,
	Dropdown,
	ErrorMessage,
	frappeRequest,
	LoadingIndicator,
	TabButtons,
} from "frappe-ui"
import MetricTile from "@/components/Insights/MetricTile/MetricTile.vue"
import PerformanceReportChart from "@/components/Insights/PerformanceReportChart/PerformanceReportChart.vue"
import { openReportExport } from "@/utils/exportReport"
import { Icon } from "@iconify/vue"
import { dayjs } from "@/dayjs"
import RunTree from "@/components/Insights/RunTree/RunTree.vue"
import {
	fmtCompact,
	fmtCurrency,
	fmtCurrencyExact,
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

const expandedRow = ref(null)
const recentRuns = ref([])
const recentRunsLoading = ref(false)
const recentRunsError = ref(null)

const expandedStepRun = ref(null)
const tree = ref(null)
const treeError = ref(null)

function formatDate(dateStr) {
	if (!dateStr) return ""
	return dayjs(dateStr).format("DD-MM-YYYY hh:mm A")
}

async function toggleExpand(idx) {
	if (expandedRow.value === idx) {
		expandedRow.value = null
		recentRuns.value = []
		expandedStepRun.value = null
		tree.value = null
		return
	}

	expandedRow.value = idx
	expandedStepRun.value = null
	tree.value = null
	const row = reportData.value.rows[idx]

	recentRunsLoading.value = true
	recentRunsError.value = null
	try {
		// Top-level runs only, each with its sub-runs rolled up.
		// The "model" column holds the agent name when grouped by agent.
		const params = { status: "Success", limit: 10 }
		if (row.model) {
			if (groupBy.value === "agent") params.agent_configuration = row.model
			else params.model = row.model
		}
		if (row.bpmn_id) params.bpmn_id = row.bpmn_id

		const response = await frappeRequest({
			url: "/api/method/one_bpmn.api.insights.get_recent_runs",
			method: "POST",
			params,
		})
		recentRuns.value = response || []
	} catch (err) {
		recentRunsError.value = err
		recentRuns.value = []
	} finally {
		recentRunsLoading.value = false
	}
}

async function toggleSteps(ri, runName) {
	if (expandedStepRun.value === ri) {
		expandedStepRun.value = null
		tree.value = null
		return
	}

	expandedStepRun.value = ri
	tree.value = null
	treeError.value = null
	try {
		const response = await frappeRequest({
			url: "/api/method/one_bpmn.api.insights.get_run_tree",
			method: "POST",
			params: { run_name: runName },
		})
		tree.value = response || null
	} catch (err) {
		treeError.value = err
	}
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

function download(fmt) {
	openReportExport("one_bpmn.api.insights.export_latency_report", { ...queryParams(), fmt })
}

async function fetchReport() {
	loading.value = true
	error.value = null
	try {
		const response = await frappeRequest({
			url: "/api/method/one_bpmn.api.insights.get_performance_report",
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

function runTokensTitle(run) {
	const total = fmtNum(run.tree_total_tokens ?? run.total_tokens)
	return run.child_runs ? `${total}, this run alone: ${fmtNum(run.total_tokens)}` : total
}

function runCostTitle(run) {
	const total = fmtCurrencyExact(run.tree_estimated_cost ?? run.estimated_cost)
	return run.child_runs ? `${total}, this run alone: ${fmtCurrencyExact(run.estimated_cost)}` : total
}
</script>

<style scoped>
</style>
