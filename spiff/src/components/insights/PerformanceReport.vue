<template>
	<div class="space-y-6">
		<div class="flex flex-wrap gap-3 items-center justify-between">
			<TabButtons
				v-model="groupBy"
				:buttons="GROUP_BY_BUTTONS"
			/>
			<FormControl
				v-model="filterBpmnId"
				type="text"
				placeholder="Filter by BPMN Element ID"
				class="w-56"
				@update:model-value="debouncedFetch"
			/>
		</div>

		<!-- Loading State -->
		<div v-if="loading" class="flex items-center justify-center h-64">
			<div class="text-gray-500">Loading...</div>
		</div>

		<!-- Empty State -->
		<div v-else-if="!reportData.rows || reportData.rows.length === 0" class="flex flex-col items-center justify-center h-64 text-center">
			<div class="text-gray-400 mb-4">
				<Icon icon="lucide:timer" class="w-16 h-16 mx-auto" />
			</div>
			<h3 class="text-lg font-medium text-gray-900 mb-1">No Performance Data</h3>
			<p class="text-gray-500">No successful agent runs found for the selected period.</p>
		</div>

		<template v-else>
			<div
				v-if="trend.labels && trend.labels.length > 0"
				class="bg-gray-50 rounded-lg p-4"
			>
				<div class="text-xs text-gray-500 uppercase tracking-wide mb-3">Latency Trend (p50 / p95)</div>
				<div class="latency-chart h-[180px]">
					<AxisChart :config="trendConfig" />
				</div>
			</div>

			<!-- Main Table -->
			<div class="overflow-x-auto">
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
													<!-- WI-002190: the turn's total, sub-runs included; the run's own figure on hover -->
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

												<!-- Steps detail: the run as a tree (WI-002190) -->
												<tr v-if="expandedStepRun === ri && tree">
													<td colspan="8" class="bg-white p-3">
														<RunTree :node="tree" />
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
import { AxisChart, Badge, FormControl, frappeRequest, TabButtons } from "frappe-ui"
import { Icon } from "@iconify/vue"
import { dayjs } from "@/dayjs"
import RunTree from "@/components/insights/RunTree.vue"
import { fmtInt as fmtNum, fmtCompact, fmtCurrency, fmtCurrencyExact, fmtDuration } from "@/utils/formatters"

const props = defineProps({
	fromDate: String,
	toDate: String,
	origin: { type: String, default: "production" },
	model: { type: String, default: "" },
	provider: { type: String, default: "" },
	processModel: { type: String, default: "" },
})

const GROUP_BY_BUTTONS = [
	{ label: "By model", value: "model" },
	{ label: "By AI agent", value: "agent" },
]

const loading = ref(false)
const reportData = ref({})
const filterBpmnId = ref("")
const groupBy = ref("model")

const expandedRow = ref(null)
const recentRuns = ref([])
const recentRunsLoading = ref(false)

const expandedStepRun = ref(null)
const tree = ref(null)

function formatDate(dateStr) {
	if (!dateStr) return ""
	return dayjs(dateStr).format("DD-MM-YYYY hh:mm A")
}

const trend = computed(() => reportData.value.trend || { labels: [], p50: [], p95: [] })

const trendConfig = computed(() => ({
	data: trend.value.labels.map((date, i) => ({ date, p50: trend.value.p50[i], p95: trend.value.p95[i] })),
	xAxis: {
		key: "date",
		type: "time",
		timeGrain: "day",
		echartOptions: { axisLabel: { formatter: (v) => dayjs(v).format("MMM D") } },
	},
	yAxis: { echartOptions: { name: "", axisLabel: { formatter: (v) => fmtDuration(v) } } },
	series: [
		{ name: "p50", type: "line", color: "#2563eb", showDataPoints: true },
		{ name: "p95", type: "line", color: "#d97706", showDataPoints: true },
	],
	echartOptions: {
		tooltip: {
			confine: true,
			formatter: (params) =>
				[
					`<div class="font-medium mb-1">${dayjs(params[0]?.value?.[0]).format("MMM D")}</div>`,
					...params.map((p) => `<div class="flex justify-between gap-5"><span>${p.seriesName}</span><span>${fmtDuration(p.value?.[1])}</span></div>`),
				].join(""),
		},
		grid: { bottom: 30 },
	},
}))

let fetchTimer = null
function debouncedFetch() {
	if (fetchTimer) clearTimeout(fetchTimer)
	fetchTimer = setTimeout(fetchReport, 400)
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
	try {
		// WI-002190: top-level runs only, each with its sub-runs rolled up.
		// The "model" column holds the agent name when grouped by agent.
		const params = { status: "Success", limit: 10 }
		if (row.model) {
			if (groupBy.value === "agent") params.agent_configuration = row.model
			else params.model = row.model
		}
		if (row.bpmn_id) params.bpmn_id = row.bpmn_id

		const response = await frappeRequest({
			url: "/api/method/one_bpmn.api.insights_api.get_recent_runs",
			method: "POST",
			params,
		})
		recentRuns.value = response || []
	} catch (error) {
		console.error("Failed to fetch recent runs:", error)
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
	try {
		const response = await frappeRequest({
			url: "/api/method/one_bpmn.api.insights_api.get_run_tree",
			method: "POST",
			params: { run_name: runName },
		})
		tree.value = response || null
	} catch (error) {
		console.error("Failed to fetch run tree:", error)
		tree.value = null
	}
}

async function fetchReport() {
	loading.value = true
	try {
		const params = {}
		if (props.fromDate) params.from_date = props.fromDate
		if (props.toDate) params.to_date = props.toDate
		if (props.model) params.model = props.model
		if (props.provider) params.provider = props.provider
		if (props.processModel) params.process_model = props.processModel
		if (filterBpmnId.value) params.bpmn_id = filterBpmnId.value
		params.origin = props.origin
		params.group_by = groupBy.value

		const response = await frappeRequest({
			url: "/api/method/one_bpmn.api.insights_api.get_performance_report",
			method: "POST",
			params,
		})
		reportData.value = response || {}
	} catch (error) {
		console.error("Failed to fetch performance report:", error)
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
.latency-chart :deep(div[class*="min-h-[300px]"]) {
	min-height: 0;
	min-width: 0;
}
</style>
