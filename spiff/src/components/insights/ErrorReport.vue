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
					:disabled="loading || !summary.errors"
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
				icon="lucide:bar-chart-3"
				class="w-12 h-12 text-gray-400 mb-3"
			/>
			<h3 class="text-base font-medium text-gray-900">{{ __("No runs in this range") }}</h3>
			<p class="text-sm text-gray-500">{{ __("Try a wider date range or different filters") }}</p>
		</div>

		<template v-else>
			<div class="grid grid-cols-2 sm:grid-cols-3 gap-px bg-gray-200 border border-gray-200 rounded-lg overflow-hidden">
				<MetricTile
					:label="__('Error rate')"
					:value="fmtPct(summary.error_rate)"
					:value-class="summary.error_rate > 0 ? 'text-red-600' : 'text-gray-900'"
					:delta="summary.delta_pt ?? null"
					delta-kind="pt"
					good-direction="down"
					:subtitle="priorDates"
				/>
				<MetricTile
					:label="__('Errors')"
					:value="fmtNum(summary.errors)"
					:delta="summary.errors_delta ?? null"
					good-direction="down"
					:subtitle="errorsSubtitle"
				/>
				<MetricTile
					class="col-span-2 sm:col-span-1"
					:label="__('Retry recovery')"
					:value="fmtPct(summary.retry_recovery_rate, 0)"
					:delta="summary.retry_recovery_delta_pt ?? null"
					delta-kind="pt"
					good-direction="up"
					:subtitle="retrySubtitle"
				/>
			</div>

			<div
				v-if="!summary.errors"
				class="flex flex-col items-center justify-center h-48 text-center"
			>
				<Icon
					icon="lucide:check-circle"
					class="w-12 h-12 text-green-500 mb-3"
				/>
				<p class="text-sm text-gray-700">{{ __("No errors in") }} {{ fmtNum(summary.runs) }} {{ __("runs") }}</p>
			</div>

			<template v-else>
				<ErrorReportChart
					:timeseries="reportData.timeseries || {}"
					:codes="reportData.codes || []"
					:grain="reportData.grain"
					:from-date="reportData.from_date"
					:to-date="reportData.to_date"
					:selected-code="errorCode"
					@select="errorCode = $event"
				/>

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
								<td class="py-3 px-3 text-sm text-gray-600">{{ row.bpmn_label || row.bpmn_id || "-" }}</td>
								<td class="py-3 px-3 text-sm text-gray-600 text-right">{{ fmtNum(row.total_runs) }}</td>
								<td class="py-3 px-3 text-sm text-gray-600 text-right">{{ fmtNum(row.successes) }}</td>
								<td class="py-3 px-3 text-sm text-right font-medium" :class="row.errors > 0 ? 'text-red-600' : 'text-gray-600'">
									{{ fmtNum(row.errors) }}
								</td>
								<td class="py-3 px-3 text-sm text-right font-medium" :class="rateColor(row.success_rate)">
									{{ fmtPct(row.success_rate) }}
								</td>
								<td class="py-3 px-3 text-sm text-gray-600 text-right">{{ fmtPct(row.retry_rate) }}</td>
								<td class="py-3 px-3 text-sm text-gray-600 text-right">{{ fmtNum(row.retry_recovered) }}</td>
								<td class="py-3 px-3 text-sm text-gray-600 text-right">{{ fmtDuration(row.avg_duration_ms) }}</td>
							</tr>
						</tbody>
					</table>
				</div>
			</template>
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
import { Icon } from "@iconify/vue"
import { dayjs } from "@/dayjs"
import ErrorReportChart from "@/components/insights/ErrorReportChart.vue"
import MetricTile from "@/components/insights/MetricTile.vue"
import { fmtInt as fmtNum, fmtDuration, fmtPct } from "@/utils/formatters"

const props = defineProps({
	fromDate: { type: String, default: "" },
	toDate: { type: String, default: "" },
	origin: { type: String, default: "production" },
	model: { type: String, default: "" },
	provider: { type: String, default: "" },
	processModel: { type: String, default: "" },
})

const __ = (window.__ && typeof window.__ === "function") ? window.__ : (s) => s

const groupByButtons = [
	{ label: __("By model"), value: "model" },
	{ label: __("By AI agent"), value: "agent" },
]

const loading = ref(false)
const error = ref(null)
const reportData = ref({})
const groupBy = ref("model")
const errorCode = ref("")

const summary = computed(() => reportData.value.summary || {})

const priorDates = computed(() => {
	const from = dayjs(reportData.value.previous_from)
	const to = dayjs(reportData.value.previous_to)
	if (!from.isValid() || !to.isValid()) return ""
	const end = from.isSame(to, "month") ? to.format("D") : to.format("MMM D")
	return `${__("vs")} ${from.format("MMM D")} ${__("to")} ${end}`
})
const errorsSubtitle = computed(() => {
	const text = `${__("of")} ${fmtNum(summary.value.runs)} ${__("runs")}`
	return summary.value.suspended ? `${text} · ${fmtNum(summary.value.suspended)} ${__("suspended")}` : text
})
const retrySubtitle = computed(
	() =>
		`${fmtNum(summary.value.retry_recovered)} ${__("of")} ${fmtNum(summary.value.retried)} ${__("retried runs recovered")}`,
)

const exportOptions = computed(() => [
	{ label: "CSV", onClick: () => download("csv") },
	{ label: "XLSX", onClick: () => download("xlsx") },
])

function rateColor(rate) {
	if (rate >= 95) return "text-green-600"
	if (rate >= 85) return "text-yellow-600"
	return "text-red-600"
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
		error_code: errorCode.value,
	}
}

// The export endpoint replies with a file, so the browser navigates to it instead of fetching.
function download(fmt) {
	const params = new URLSearchParams({ ...queryParams(), fmt })
	window.open(`/api/method/one_bpmn.api.insights_api.export_error_report?${params.toString()}`, "_blank")
}

async function fetchReport() {
	loading.value = true
	error.value = null
	try {
		const response = await frappeRequest({
			url: "/api/method/one_bpmn.api.insights_api.get_error_report",
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

watch(() => [props.fromDate, props.toDate, props.origin, props.model, props.provider, props.processModel, groupBy.value, errorCode.value], fetchReport)
onMounted(fetchReport)
</script>
