<template>
	<div class="space-y-6">
		<!-- Filters -->
		<div class="flex flex-wrap gap-4 items-center">
			<FormControl
				type="select"
				v-model="filterModel"
				:options="modelOptions"
				class="w-48"
				@change="fetchReport"
			/>
			<FormControl
				type="text"
				v-model="filterBpmnId"
				placeholder="Filter by BPMN Element ID"
				class="w-56"
				@update:model-value="debouncedFetch"
			/>
			<FormControl
				type="select"
				v-model="filterProcess"
				:options="processOptions"
				class="w-48"
				@change="fetchReport"
			/>
			<!-- WI-001608: AI tasks are done by AI Agents -->
			<FormControl
				type="select"
				v-model="groupBy"
				:options="[
					{ label: 'Group by Model', value: 'model' },
					{ label: 'Group by AI Agent', value: 'agent' },
				]"
				class="w-48"
				@change="fetchReport"
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
			<!-- Trend -->
			<div v-if="trend.labels && trend.labels.length > 0" class="bg-gray-50 rounded-lg p-4">
				<div class="text-xs text-gray-500 uppercase tracking-wide mb-3">Latency Trend (p50 / p95)</div>
				<div class="overflow-x-auto">
					<svg :width="trendWidth" height="120" class="block">
						<template v-for="(label, i) in trend.labels" :key="i">
							<rect
								:x="50 + i * 40"
								:y="100 - trendBarH(trend.p95[i])"
								width="24"
								:height="trendBarH(trend.p95[i])"
								fill="#fde68a"
								rx="2"
							>
								<title>p95: {{ fmtNum(trend.p95[i]) }}ms ({{ label }})</title>
							</rect>
							<rect
								:x="50 + i * 40"
								:y="100 - trendBarH(trend.p50[i])"
								width="24"
								:height="trendBarH(trend.p50[i])"
								fill="#6366f1"
								rx="2"
							>
								<title>p50: {{ fmtNum(trend.p50[i]) }}ms ({{ label }})</title>
							</rect>
							<text
								:x="50 + i * 40 + 12"
								y="116"
								text-anchor="middle"
								class="fill-gray-400"
								font-size="10"
							>{{ label.slice(5) }}</text>
						</template>
					</svg>
				</div>
				<div class="flex gap-4 mt-2">
					<div class="flex items-center gap-1.5">
						<div class="w-3 h-3 rounded-sm bg-indigo-500"></div>
						<span class="text-xs text-gray-600">p50</span>
					</div>
					<div class="flex items-center gap-1.5">
						<div class="w-3 h-3 rounded-sm bg-yellow-200"></div>
						<span class="text-xs text-gray-600">p95</span>
					</div>
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
								<td class="py-3 px-3 text-sm text-gray-600 text-right">{{ fmtNum(row.avg_duration_ms) }}ms</td>
								<td class="py-3 px-3 text-sm text-gray-600 text-right">{{ fmtNum(row.p50_duration_ms) }}ms</td>
								<td class="py-3 px-3 text-sm text-right font-medium" :class="row.p95_duration_ms > 5000 ? 'text-red-600' : 'text-gray-600'">
									{{ fmtNum(row.p95_duration_ms) }}ms
								</td>
								<td class="py-3 px-3 text-sm text-gray-600 text-right">{{ fmtNum(row.max_duration_ms) }}ms</td>
								<td class="py-3 px-3 text-sm text-gray-600 text-right">{{ row.avg_steps }}</td>
								<td class="py-3 px-3 text-sm text-gray-600 text-right">{{ fmtNum(row.avg_tokens) }}</td>
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
													<td class="py-2 px-2 text-xs text-gray-600 font-mono">{{ run.name }}</td>
													<td class="py-2 px-2">
														<Badge :theme="run.status === 'Success' ? 'green' : 'red'" size="sm">{{ run.status }}</Badge>
													</td>
													<td class="py-2 px-2 text-xs text-gray-600 text-right">{{ fmtNum(run.duration_ms) }}ms</td>
													<td class="py-2 px-2 text-xs text-gray-600 text-right">{{ fmtNum(run.total_tokens) }}</td>
													<td class="py-2 px-2 text-xs text-gray-600 text-right">${{ (run.estimated_cost ?? 0).toFixed(4) }}</td>
													<td class="py-2 px-2 text-xs text-gray-500">{{ formatDate(run.started_at) }}</td>
												</tr>

												<!-- Steps detail -->
												<tr v-if="expandedStepRun === ri && steps.length > 0">
													<td colspan="7" class="bg-white p-3">
														<table class="w-full">
															<thead>
																<tr class="border-b border-gray-200">
																	<th class="text-left text-xs text-gray-400 font-medium py-1 px-2">Step</th>
																	<th class="text-left text-xs text-gray-400 font-medium py-1 px-2">Role</th>
																	<th class="text-left text-xs text-gray-400 font-medium py-1 px-2">Tool</th>
																	<th class="text-right text-xs text-gray-400 font-medium py-1 px-2">Latency</th>
																	<th class="text-right text-xs text-gray-400 font-medium py-1 px-2">Tokens</th>
																	<th class="text-right text-xs text-gray-400 font-medium py-1 px-2">Cost</th>
																</tr>
															</thead>
															<tbody>
																<tr v-for="step in steps" :key="step.step_index" class="border-b border-gray-50">
																	<td class="py-1.5 px-2 text-xs text-gray-500">{{ step.step_index }}</td>
																	<td class="py-1.5 px-2 text-xs text-gray-600">{{ step.role }}</td>
																	<td class="py-1.5 px-2 text-xs text-gray-600 font-mono">{{ step.tool_name || "—" }}</td>
																	<td class="py-1.5 px-2 text-xs text-gray-600 text-right">{{ fmtNum(step.latency_ms) }}ms</td>
																	<td class="py-1.5 px-2 text-xs text-gray-600 text-right">{{ fmtNum((step.prompt_tokens ?? 0) + (step.completion_tokens ?? 0)) }}</td>
																	<td class="py-1.5 px-2 text-xs text-gray-600 text-right">${{ (step.cost ?? 0).toFixed(4) }}</td>
																</tr>
															</tbody>
														</table>
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
import { frappeRequest, FormControl, Badge } from "frappe-ui"
import { Icon } from "@iconify/vue"
import { dayjs } from "@/dayjs"

const props = defineProps({
	fromDate: String,
	toDate: String,
})

const loading = ref(false)
const reportData = ref({})
const filterModel = ref("")
const filterBpmnId = ref("")
const filterProcess = ref("")
const groupBy = ref("model") // "model" | "agent" (WI-001608)
const cachedProcesses = ref([])
const cachedModels = ref([])

const expandedRow = ref(null)
const recentRuns = ref([])
const recentRunsLoading = ref(false)

const expandedStepRun = ref(null)
const steps = ref([])

const numFormatter = new Intl.NumberFormat("en-US")
function fmtNum(val) { return numFormatter.format(val ?? 0) }

function formatDate(dateStr) {
	if (!dateStr) return ""
	return dayjs(dateStr).format("DD-MM-YYYY hh:mm A")
}

const trend = computed(() => reportData.value.trend || { labels: [], p50: [], p95: [] })

const maxTrendVal = computed(() => {
	let max = 0
	for (const v of (trend.value.p95 || [])) { if (v > max) max = v }
	return max || 1
})

const trendWidth = computed(() => 60 + (trend.value.labels?.length || 0) * 40)

function trendBarH(value) {
	if (!value || !maxTrendVal.value) return 0
	return Math.max((value / maxTrendVal.value) * 80, 2)
}

const modelOptions = computed(() => {
	return [{ label: "All Models", value: "" }, ...cachedModels.value.map(m => ({ label: m, value: m }))]
})

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
		steps.value = []
		return
	}

	expandedRow.value = idx
	expandedStepRun.value = null
	steps.value = []
	const row = reportData.value.rows[idx]

	recentRunsLoading.value = true
	try {
		const filters = { status: "Success" }
		if (row.model) filters.model = row.model
		if (row.bpmn_id) filters.bpmn_id = row.bpmn_id

		const response = await frappeRequest({
			url: "/api/method/frappe.client.get_list",
			method: "POST",
			params: {
				doctype: "AI Agent Run",
				filters: JSON.stringify(filters),
				fields: JSON.stringify(["name", "status", "duration_ms", "total_tokens", "estimated_cost", "started_at"]),
				order_by: "started_at desc",
				limit_page_length: 10,
			},
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
		steps.value = []
		return
	}

	expandedStepRun.value = ri
	try {
		const response = await frappeRequest({
			url: "/api/method/one_bpmn.api.insights_api.get_run_steps",
			method: "POST",
			params: { run_name: runName },
		})
		steps.value = response || []
	} catch (error) {
		console.error("Failed to fetch run steps:", error)
		steps.value = []
	}
}

async function fetchReport() {
	loading.value = true
	try {
		const params = {}
		if (props.fromDate) params.from_date = props.fromDate
		if (props.toDate) params.to_date = props.toDate
		if (filterModel.value) params.model = filterModel.value
		if (filterBpmnId.value) params.bpmn_id = filterBpmnId.value
		if (filterProcess.value) params.process_model = filterProcess.value
		params.group_by = groupBy.value

		const response = await frappeRequest({
			url: "/api/method/one_bpmn.api.insights_api.get_performance_report",
			method: "POST",
			params,
		})
		reportData.value = response || {}

		// Only model-grouped rows may feed the Model filter options —
		// agent names must not leak in (WI-001608).
		if (groupBy.value === "model" && !filterModel.value) {
			cachedModels.value = [...new Set((reportData.value.rows || []).map(r => r.model))].sort()
		}

		// Load process options on first fetch
		if (!cachedProcesses.value.length) {
			await loadProcessOptions()
		}
	} catch (error) {
		console.error("Failed to fetch performance report:", error)
		reportData.value = {}
	} finally {
		loading.value = false
	}
}

const processOptions = computed(() => {
	return [{ label: "All Processes", value: "" }, ...cachedProcesses.value.map(p => ({ label: p, value: p }))]
})

async function loadProcessOptions() {
	try {
		const result = await frappeRequest({
			url: "/api/method/frappe.client.get_list",
			method: "POST",
			params: {
				doctype: "BPMN Process Model",
				fields: ["name"],
				order_by: "name asc",
				limit_page_length: 0,
			},
		})
		cachedProcesses.value = (result || []).map(r => r.name).sort()
	} catch (e) {
		console.error("Failed to load process models:", e)
	}
}

watch(() => [props.fromDate, props.toDate], fetchReport)
onMounted(fetchReport)
</script>
