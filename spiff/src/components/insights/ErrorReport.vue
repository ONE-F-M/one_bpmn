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
				v-model="filterErrorCode"
				:options="errorCodeOptions"
				class="w-56"
				@change="fetchReport"
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
				<Icon icon="lucide:check-circle" class="w-16 h-16 mx-auto" />
			</div>
			<h3 class="text-lg font-medium text-gray-900 mb-1">No Error Data</h3>
			<p class="text-gray-500">No agent runs found for the selected period.</p>
		</div>

		<template v-else>
			<!-- Summary -->
			<div class="grid grid-cols-2 lg:grid-cols-4 gap-4">
				<div class="bg-gray-50 rounded-lg p-4">
					<div class="text-xs text-gray-500 uppercase tracking-wide mb-1">Total Errors</div>
					<div class="text-lg font-bold" :class="summary.total_errors > 0 ? 'text-red-600' : 'text-gray-900'">
						{{ fmtNum(summary.total_errors) }}
					</div>
				</div>
				<div class="bg-gray-50 rounded-lg p-4">
					<div class="text-xs text-gray-500 uppercase tracking-wide mb-1">Most Common Error</div>
					<div class="text-sm font-bold text-gray-900 truncate">{{ summary.most_common_error || "—" }}</div>
				</div>
				<div class="bg-gray-50 rounded-lg p-4">
					<div class="text-xs text-gray-500 uppercase tracking-wide mb-1">Worst Element</div>
					<div class="text-sm font-bold text-gray-900 truncate">{{ summary.worst_element || "—" }}</div>
				</div>
				<div class="bg-gray-50 rounded-lg p-4">
					<div class="text-xs text-gray-500 uppercase tracking-wide mb-1">Retry Recovery</div>
					<div class="text-lg font-bold text-gray-900">{{ (summary.retry_recovery_rate ?? 0).toFixed(1) }}%</div>
				</div>
			</div>

			<!-- Error breakdown badges -->
			<div v-if="errorBreakdown.length > 0" class="flex flex-wrap gap-2">
				<Badge
					v-for="eb in errorBreakdown"
					:key="eb.error_code"
					theme="red"
					size="sm"
				>
					{{ eb.error_code }}: {{ eb.count }}
				</Badge>
			</div>

			<!-- Table -->
			<div class="overflow-x-auto">
				<table class="w-full">
					<thead>
						<tr class="border-b border-gray-200">
							<th class="text-left text-xs uppercase text-gray-500 font-medium py-2 px-3">{{ groupBy === "agent" ? "AI Agent" : "Model" }}</th>
							<th class="text-left text-xs uppercase text-gray-500 font-medium py-2 px-3">BPMN Element</th>
							<th class="text-right text-xs uppercase text-gray-500 font-medium py-2 px-3">Total Runs</th>
							<th class="text-right text-xs uppercase text-gray-500 font-medium py-2 px-3">Successes</th>
							<th class="text-right text-xs uppercase text-gray-500 font-medium py-2 px-3">Errors</th>
							<th class="text-right text-xs uppercase text-gray-500 font-medium py-2 px-3">Success Rate</th>
							<th class="text-right text-xs uppercase text-gray-500 font-medium py-2 px-3">Retry Rate</th>
							<th class="text-right text-xs uppercase text-gray-500 font-medium py-2 px-3">Recovered</th>
							<th class="text-right text-xs uppercase text-gray-500 font-medium py-2 px-3">Avg Duration</th>
						</tr>
					</thead>
					<tbody>
						<tr v-for="(row, idx) in reportData.rows" :key="idx" class="border-b border-gray-100 hover:bg-gray-50 transition-colors">
							<td class="py-3 px-3 text-sm text-gray-900 font-medium">{{ row.model }}</td>
							<td class="py-3 px-3 text-sm text-gray-600">{{ row.bpmn_label || row.bpmn_id || "—" }}</td>
							<td class="py-3 px-3 text-sm text-gray-600 text-right">{{ fmtNum(row.total_runs) }}</td>
							<td class="py-3 px-3 text-sm text-gray-600 text-right">{{ fmtNum(row.successes) }}</td>
							<td class="py-3 px-3 text-sm text-right font-medium" :class="row.errors > 0 ? 'text-red-600' : 'text-gray-600'">
								{{ fmtNum(row.errors) }}
							</td>
							<td class="py-3 px-3 text-sm text-right font-medium" :class="rateColor(row.success_rate)">
								{{ row.success_rate.toFixed(1) }}%
							</td>
							<td class="py-3 px-3 text-sm text-gray-600 text-right">{{ row.retry_rate.toFixed(1) }}%</td>
							<td class="py-3 px-3 text-sm text-gray-600 text-right">{{ fmtNum(row.retry_recovered) }}</td>
							<td class="py-3 px-3 text-sm text-gray-600 text-right">{{ fmtNum(row.avg_duration_ms) }}ms</td>
						</tr>
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

const props = defineProps({
	fromDate: String,
	toDate: String,
})

const loading = ref(false)
const reportData = ref({})
const filterModel = ref("")
const filterErrorCode = ref("")
const filterProcess = ref("")
const groupBy = ref("model") // "model" | "agent" (WI-001608)

// Cache model options from the initial (unfiltered) load
const cachedModels = ref([])
const cachedProcesses = ref([])

const numFormatter = new Intl.NumberFormat("en-US")
function fmtNum(val) { return numFormatter.format(val ?? 0) }

function rateColor(rate) {
	if (rate >= 95) return "text-green-600"
	if (rate >= 85) return "text-yellow-600"
	return "text-red-600"
}

const summary = computed(() => reportData.value.summary || {})
const errorBreakdown = computed(() => reportData.value.error_breakdown || [])

const modelOptions = computed(() => {
	return [{ label: "All Models", value: "" }, ...cachedModels.value.map(m => ({ label: m, value: m }))]
})

const errorCodeOptions = [
	{ label: "All Error Codes", value: "" },
	{ label: "FAILED_MODEL_CALL", value: "FAILED_MODEL_CALL" },
	{ label: "SCHEMA_VALIDATION_FAILED", value: "SCHEMA_VALIDATION_FAILED" },
	{ label: "TIMEOUT", value: "TIMEOUT" },
	{ label: "UNEXPECTED_ERROR", value: "UNEXPECTED_ERROR" },
	{ label: "PROVIDER_NOT_FOUND", value: "PROVIDER_NOT_FOUND" },
	{ label: "PROVIDER_DISABLED", value: "PROVIDER_DISABLED" },
]

async function fetchReport() {
	loading.value = true
	try {
		const params = {}
		if (props.fromDate) params.from_date = props.fromDate
		if (props.toDate) params.to_date = props.toDate
		if (filterModel.value) params.model = filterModel.value
		if (filterErrorCode.value) params.error_code = filterErrorCode.value
		if (filterProcess.value) params.process_model = filterProcess.value
		params.group_by = groupBy.value

		const response = await frappeRequest({
			url: "/api/method/one_bpmn.api.insights_api.get_error_report",
			method: "POST",
			params,
		})
		reportData.value = response || {}

		// Refresh cached model options only on unfiltered, model-grouped
		// fetches — agent names must not leak into the Model filter.
		if (!filterModel.value && !filterErrorCode.value && !filterProcess.value && groupBy.value === "model") {
			const rows = reportData.value.rows || []
			cachedModels.value = [...new Set(rows.map(r => r.model))].sort()
		}
		// Refresh process list from a separate call on initial load
		if (!cachedProcesses.value.length) {
			await loadProcessOptions()
		}
	} catch (error) {
		console.error("Failed to fetch error report:", error)
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
