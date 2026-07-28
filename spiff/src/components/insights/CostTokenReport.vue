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
				type="select"
				v-model="filterProvider"
				:options="providerOptions"
				class="w-48"
				@change="fetchReport"
			/>
			<FormControl
				type="select"
				v-model="filterProcess"
				:options="processOptions"
				class="w-48"
				@change="fetchReport"
			/>
			<!-- WI-001608: AI tasks are done by AI Agents — group the report
			     by the run's AI Agent Configuration instead of by model. -->
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
				<Icon icon="lucide:bar-chart-3" class="w-16 h-16 mx-auto" />
			</div>
			<h3 class="text-lg font-medium text-gray-900 mb-1">No Cost Data</h3>
			<p class="text-gray-500">No agent runs found for the selected period.</p>
		</div>

		<template v-else>
			<!-- Summary -->
			<div class="grid grid-cols-3 gap-4">
				<div class="bg-gray-50 rounded-lg p-4">
					<div class="text-xs text-gray-500 uppercase tracking-wide mb-1">Total Cost</div>
					<div class="text-lg font-bold text-gray-900">{{ fmtCurrency(reportData.summary?.total_cost) }}</div>
				</div>
				<div class="bg-gray-50 rounded-lg p-4">
					<div class="text-xs text-gray-500 uppercase tracking-wide mb-1">Total Runs</div>
					<div class="text-lg font-bold text-gray-900">{{ fmtNum(reportData.summary?.total_runs) }}</div>
				</div>
				<div class="bg-gray-50 rounded-lg p-4">
					<div class="text-xs text-gray-500 uppercase tracking-wide mb-1">Total Tokens</div>
					<div class="text-lg font-bold text-gray-900">{{ fmtNum(reportData.summary?.total_tokens) }}</div>
				</div>
			</div>

			<!-- Chart -->
			<div v-if="chartData.labels && chartData.labels.length > 0" class="bg-gray-50 rounded-lg p-4">
				<div class="text-xs text-gray-500 uppercase tracking-wide mb-3">Daily Cost by Model</div>
				<div class="overflow-x-auto">
					<svg :width="chartWidth" height="200" class="block">
						<line x1="40" y1="10" x2="40" :y2="chartHeight" stroke="#e5e7eb" stroke-width="1" />
						<template v-for="(dateLabel, di) in chartData.labels" :key="di">
							<template v-for="(ds, mi) in chartData.datasets" :key="mi">
								<rect
									:x="barX(di, mi)"
									:y="chartHeight - barHeight(ds.values[di])"
									:width="barW"
									:height="barHeight(ds.values[di])"
									:fill="palette[mi % palette.length]"
									rx="2"
								>
									<title>{{ ds.model }}: ${{ ds.values[di]?.toFixed(4) }} ({{ dateLabel }})</title>
								</rect>
							</template>
							<text
								:x="barX(di, 0) + (barW * chartData.datasets.length) / 2"
								:y="chartHeight + 16"
								text-anchor="middle"
								class="fill-gray-400"
								font-size="10"
							>{{ dateLabel.slice(5) }}</text>
						</template>
					</svg>
				</div>
				<div class="flex flex-wrap gap-4 mt-3">
					<div v-for="(ds, mi) in chartData.datasets" :key="mi" class="flex items-center gap-1.5">
						<div class="w-3 h-3 rounded-sm" :style="{ backgroundColor: palette[mi % palette.length] }"></div>
						<span class="text-xs text-gray-600">{{ ds.model }}</span>
					</div>
				</div>
			</div>

			<!-- Table -->
			<div class="overflow-x-auto">
				<table class="w-full">
					<thead>
						<tr class="border-b border-gray-200">
							<th class="text-left text-xs uppercase text-gray-500 font-medium py-2 px-3">Date</th>
							<th class="text-left text-xs uppercase text-gray-500 font-medium py-2 px-3">{{ groupBy === "agent" ? "AI Agent" : "Model" }}</th>
							<th class="text-left text-xs uppercase text-gray-500 font-medium py-2 px-3">Provider</th>
							<th class="text-right text-xs uppercase text-gray-500 font-medium py-2 px-3">Runs</th>
							<th class="text-right text-xs uppercase text-gray-500 font-medium py-2 px-3">Tokens</th>
							<th class="text-right text-xs uppercase text-gray-500 font-medium py-2 px-3">Avg Tokens</th>
							<th class="text-right text-xs uppercase text-gray-500 font-medium py-2 px-3">Total Cost</th>
							<th class="text-right text-xs uppercase text-gray-500 font-medium py-2 px-3">Avg Cost</th>
							<th class="text-right text-xs uppercase text-gray-500 font-medium py-2 px-3">Input Cost</th>
							<th class="text-right text-xs uppercase text-gray-500 font-medium py-2 px-3">Output Cost</th>
						</tr>
					</thead>
					<tbody>
						<tr v-for="(row, idx) in reportData.rows" :key="idx" class="border-b border-gray-100 hover:bg-gray-50 transition-colors">
							<td class="py-3 px-3 text-sm text-gray-600">{{ row.date }}</td>
							<td class="py-3 px-3 text-sm text-gray-900 font-medium">{{ row.model }}</td>
							<td class="py-3 px-3 text-sm text-gray-600">{{ row.provider }}</td>
							<td class="py-3 px-3 text-sm text-gray-600 text-right">{{ fmtNum(row.total_runs) }}</td>
							<td class="py-3 px-3 text-sm text-gray-600 text-right">{{ fmtNum(row.total_tokens) }}</td>
							<td class="py-3 px-3 text-sm text-gray-600 text-right">{{ fmtNum(row.avg_tokens) }}</td>
							<td class="py-3 px-3 text-sm text-gray-900 font-medium text-right">{{ fmtCurrency(row.total_cost) }}</td>
							<td class="py-3 px-3 text-sm text-gray-600 text-right">{{ fmtCurrency(row.avg_cost) }}</td>
							<td class="py-3 px-3 text-sm text-gray-600 text-right">{{ fmtCurrency(row.input_cost) }}</td>
							<td class="py-3 px-3 text-sm text-gray-600 text-right">{{ fmtCurrency(row.output_cost) }}</td>
						</tr>
					</tbody>
				</table>
			</div>
		</template>
	</div>
</template>

<script setup>
import { ref, computed, watch, onMounted } from "vue"
import { frappeRequest, FormControl } from "frappe-ui"
import { Icon } from "@iconify/vue"

const props = defineProps({
	fromDate: String,
	toDate: String,
})

const loading = ref(false)
const reportData = ref({})
const filterModel = ref("")
const filterProvider = ref("")
const filterProcess = ref("")
const groupBy = ref("model") // "model" | "agent" (WI-001608)

// Cache dropdown options from the initial (unfiltered) load so they
// don't shrink to only the selected value after filtering.
const cachedModels = ref([])
const cachedProviders = ref([])
const cachedProcesses = ref([])

const palette = ["#6366f1", "#8b5cf6", "#ec4899", "#f59e0b", "#10b981", "#06b6d4"]

const numFormatter = new Intl.NumberFormat("en-US")

function fmtNum(val) {
	return numFormatter.format(val ?? 0)
}

function fmtCurrency(val) {
	return "$" + (val ?? 0).toFixed(4)
}

const chartData = computed(() => reportData.value.chart_data || { labels: [], datasets: [] })
const chartHeight = 170
const barW = 12
const barGap = 2
const groupGap = 16

const maxCost = computed(() => {
	let max = 0
	for (const ds of chartData.value.datasets) {
		for (const v of ds.values) {
			if (v > max) max = v
		}
	}
	return max || 1
})

const chartWidth = computed(() => {
	const groups = chartData.value.labels?.length || 0
	const modelsPerGroup = chartData.value.datasets?.length || 1
	return 50 + groups * (modelsPerGroup * (barW + barGap) + groupGap)
})

function barX(dateIdx, modelIdx) {
	const modelsPerGroup = chartData.value.datasets?.length || 1
	const groupWidth = modelsPerGroup * (barW + barGap) + groupGap
	return 50 + dateIdx * groupWidth + modelIdx * (barW + barGap)
}

function barHeight(value) {
	if (!value || !maxCost.value) return 0
	return Math.max((value / maxCost.value) * (chartHeight - 20), 2)
}

const modelOptions = computed(() => {
	return [{ label: "All Models", value: "" }, ...cachedModels.value.map(m => ({ label: m, value: m }))]
})

const providerOptions = computed(() => {
	return [{ label: "All Providers", value: "" }, ...cachedProviders.value.map(p => ({ label: p, value: p }))]
})

async function fetchReport() {
	loading.value = true
	try {
		const params = {}
		if (props.fromDate) params.from_date = props.fromDate
		if (props.toDate) params.to_date = props.toDate
		if (filterModel.value) params.model = filterModel.value
		if (filterProvider.value) params.provider = filterProvider.value
		if (filterProcess.value) params.process_model = filterProcess.value
		params.group_by = groupBy.value

		const response = await frappeRequest({
			url: "/api/method/one_bpmn.api.insights_api.get_cost_token_report",
			method: "POST",
			params,
		})
		reportData.value = response || {}

		// Refresh cached dropdown options only on unfiltered, model-grouped
		// fetches — in agent grouping the rows' series carry agent names,
		// which must not leak into the Model filter options.
		if (!filterModel.value && !filterProvider.value && !filterProcess.value && groupBy.value === "model") {
			const rows = reportData.value.rows || []
			cachedModels.value = [...new Set(rows.map(r => r.model))].sort()
			cachedProviders.value = [...new Set(rows.map(r => r.provider))].sort()
		}
		// Refresh process list from a separate call on initial load
		if (!cachedProcesses.value.length) {
			await loadProcessOptions()
		}
	} catch (error) {
		console.error("Failed to fetch cost report:", error)
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
