<template>
	<div class="space-y-6">
		<!-- Controls -->
		<div class="flex flex-wrap gap-3 items-center justify-between">
			<div class="flex rounded-lg border border-gray-200 overflow-hidden">
				<button
					v-for="ax in axes"
					:key="ax.value"
					@click="axis = ax.value"
					class="px-3 py-1.5 text-xs font-medium transition-colors"
					:class="axis === ax.value ? 'bg-gray-900 text-white' : 'bg-white text-gray-600 hover:bg-gray-50'"
				>
					{{ ax.label }}
				</button>
			</div>

			<Dropdown :options="exportOptions" placement="right">
				<Button icon-right="chevron-down" :disabled="!rows.length">Export</Button>
			</Dropdown>
		</div>

		<!-- Pricing gap warning -->
		<div
			v-if="missingPricing.length"
			class="bg-amber-50 text-amber-800 text-sm rounded-lg px-4 py-3"
		>
			<span class="font-medium">Cost may be under-reported.</span>
			These models have no rate card on their AI Model, so their spend counts as $0.00:
			<span class="font-mono text-xs">{{ missingPricing.join(", ") }}</span>
		</div>

		<!-- Summary tiles. Scoped to the selected axis, never the whole period —
		     the label says so, and the note below reports what is excluded. -->
		<div class="grid grid-cols-2 lg:grid-cols-5 gap-4">
			<div class="bg-white rounded-lg shadow-sm p-4 border-l-4 border-purple-500">
				<div class="text-xs text-gray-500 uppercase tracking-wide font-medium">
					Cost · {{ scopeLabel }}
				</div>
				<div class="text-2xl font-bold text-gray-900">{{ fmtCost(totals.cost) }}</div>
			</div>
			<div class="bg-white rounded-lg shadow-sm p-4 border-l-4 border-amber-500">
				<div class="text-xs text-gray-500 uppercase tracking-wide font-medium">
					Tokens · {{ scopeLabel }}
				</div>
				<div class="text-2xl font-bold text-gray-900">{{ fmtNum(totals.tokens) }}</div>
			</div>
			<div class="bg-white rounded-lg shadow-sm p-4 border-l-4 border-blue-500">
				<div class="text-xs text-gray-500 uppercase tracking-wide font-medium">
					Runs · {{ scopeLabel }}
				</div>
				<div class="text-2xl font-bold text-gray-900">{{ fmtNum(totals.runs) }}</div>
			</div>
			<div class="bg-white rounded-lg shadow-sm p-4 border-l-4 border-green-500">
				<div class="text-xs text-gray-500 uppercase tracking-wide font-medium">
					{{ axis === "chat_user" ? "Users" : "Process owners" }}
				</div>
				<div class="text-2xl font-bold text-gray-900">{{ fmtNum(totals.people) }}</div>
			</div>
			<div class="bg-white rounded-lg shadow-sm p-4 border-l-4 border-cyan-500">
				<div class="text-xs text-gray-500 uppercase tracking-wide font-medium">Departments</div>
				<div class="text-2xl font-bold text-gray-900">{{ fmtNum(totals.departments) }}</div>
			</div>
		</div>

		<!-- What this axis leaves out, so the tiles are never read as the
		     period's whole AI spend. -->
		<div v-if="!loading && unshownRuns" class="text-sm text-gray-500">
			Showing {{ fmtNum(totals.runs) }} of {{ fmtNum(periodTotals.runs) }} runs
			({{ fmtCost(totals.cost) }} of {{ fmtCost(periodTotals.cost) }}) for this period.
			The other {{ fmtNum(unshownRuns) }} runs ({{ fmtCost(unshownCost) }}) are on
			<button class="underline hover:text-gray-700" @click="toggleAxis">
				{{ otherAxisLabel }}</button>.
		</div>

		<!-- Loading / empty -->
		<div v-if="loading" class="flex items-center justify-center h-48 text-gray-500">Loading…</div>
		<div v-else-if="!rows.length" class="flex flex-col items-center justify-center h-48 text-center">
			<Icon icon="lucide:receipt" class="w-12 h-12 text-gray-300 mb-3" />
			<h3 class="text-base font-medium text-gray-900">No usage in this period</h3>
			<p class="text-sm text-gray-500">Adjust the date range above.</p>
		</div>

		<!-- Table -->
		<div v-else class="overflow-x-auto">
			<table class="w-full">
				<thead>
					<tr class="border-b border-gray-200">
						<th class="text-left text-xs uppercase text-gray-500 font-medium py-2 px-3">Month</th>
						<th class="text-left text-xs uppercase text-gray-500 font-medium py-2 px-3">Department</th>
						<th class="text-left text-xs uppercase text-gray-500 font-medium py-2 px-3">
							{{ axis === "chat_user" ? "User" : "Process owner" }}
						</th>
						<th class="text-left text-xs uppercase text-gray-500 font-medium py-2 px-3">
							{{ axis === "chat_user" ? "Chat" : "Process" }}
						</th>
						<th class="text-right text-xs uppercase text-gray-500 font-medium py-2 px-3">Runs</th>
						<th class="text-right text-xs uppercase text-gray-500 font-medium py-2 px-3">Tokens</th>
						<th class="text-right text-xs uppercase text-gray-500 font-medium py-2 px-3">Cost</th>
					</tr>
				</thead>
				<tbody>
					<tr v-for="(r, i) in rows" :key="i" class="border-b border-gray-100 hover:bg-gray-50">
						<td class="py-2.5 px-3 text-sm text-gray-900 font-medium">{{ r.month }}</td>
						<td class="py-2.5 px-3 text-sm text-gray-600">{{ r.department || "—" }}</td>
						<td class="py-2.5 px-3 text-sm text-gray-600">{{ r.person || "unassigned" }}</td>
						<td class="py-2.5 px-3 text-sm text-gray-600">{{ r.subject_label || "—" }}</td>
						<td class="py-2.5 px-3 text-sm text-gray-600 text-right">{{ fmtNum(r.runs) }}</td>
						<td class="py-2.5 px-3 text-sm text-gray-600 text-right">{{ fmtNum(r.tokens) }}</td>
						<td class="py-2.5 px-3 text-sm text-gray-900 text-right font-medium">{{ fmtCost(r.cost) }}</td>
					</tr>
				</tbody>
				<tfoot>
					<tr class="border-t-2 border-gray-200">
						<td colspan="4" class="py-2.5 px-3 text-xs uppercase text-gray-500 font-medium">
							Subtotal · {{ scopeLabel }}
						</td>
						<td class="py-2.5 px-3 text-sm text-gray-900 text-right font-bold">{{ fmtNum(totals.runs) }}</td>
						<td class="py-2.5 px-3 text-sm text-gray-900 text-right font-bold">{{ fmtNum(totals.tokens) }}</td>
						<td class="py-2.5 px-3 text-sm text-gray-900 text-right font-bold">{{ fmtCost(totals.cost) }}</td>
					</tr>
				</tfoot>
			</table>
		</div>
	</div>
</template>

<script setup>
import { ref, computed, watch, onMounted } from "vue"
import { frappeRequest, Button, Dropdown } from "frappe-ui"
import { Icon } from "@iconify/vue"

const props = defineProps({
	fromDate: String,
	toDate: String,
})

const axes = [
	{ label: "By process owner", value: "process_owner" },
	{ label: "By chat user", value: "chat_user" },
]

const loading = ref(true)
const axis = ref("process_owner")
const rows = ref([])
const totals = ref({ runs: 0, tokens: 0, cost: 0, people: 0, departments: 0 })
const periodTotals = ref({ runs: 0, tokens: 0, cost: 0 })
const missingPricing = ref([])

// Each axis covers only its own half of the runs (non-chat vs chat), so the
// tiles below are a slice, never the period's whole AI spend.
const scopeLabel = computed(() =>
	axis.value === "chat_user" ? "chat users" : "process owners"
)
const otherAxisLabel = computed(() =>
	axis.value === "chat_user" ? "By process owner" : "By chat user"
)
const unshownRuns = computed(() =>
	Math.max(0, (periodTotals.value.runs || 0) - (totals.value.runs || 0))
)
const unshownCost = computed(() =>
	Math.max(0, (periodTotals.value.cost || 0) - (totals.value.cost || 0))
)

function toggleAxis() {
	axis.value = axis.value === "chat_user" ? "process_owner" : "chat_user"
}

const _num = new Intl.NumberFormat("en-US")
const _cost = new Intl.NumberFormat("en-US", {
	style: "currency", currency: "USD", minimumFractionDigits: 2, maximumFractionDigits: 4,
})
function fmtNum(n) { return _num.format(n || 0) }
function fmtCost(n) { return _cost.format(n || 0) }

// Export goes through a normal browser navigation: the endpoint replies with a
// file download, which fetch/frappeRequest can't hand to the user.
function download(fmt) {
	const params = new URLSearchParams({
		axis: axis.value,
		fmt,
		...(props.fromDate ? { from_date: props.fromDate } : {}),
		...(props.toDate ? { to_date: props.toDate } : {}),
	})
	window.open(
		`/api/method/one_bpmn.api.insights_api.export_cost_allocation?${params.toString()}`,
		"_blank"
	)
}

const exportOptions = computed(() => [
	{ label: "XLSX", icon: "file-spreadsheet", onClick: () => download("xlsx") },
	{ label: "CSV", icon: "file-text", onClick: () => download("csv") },
])

async function fetchReport() {
	loading.value = true
	try {
		const params = { axis: axis.value }
		if (props.fromDate) params.from_date = props.fromDate
		if (props.toDate) params.to_date = props.toDate
		const res = await frappeRequest({
			url: "/api/method/one_bpmn.api.insights_api.get_cost_allocation",
			method: "POST",
			params,
		})
		rows.value = res?.rows || []
		totals.value = res?.totals || { runs: 0, tokens: 0, cost: 0, people: 0, departments: 0 }
		periodTotals.value = res?.period_totals || { runs: 0, tokens: 0, cost: 0 }
		missingPricing.value = res?.models_missing_pricing || []
	} catch (e) {
		console.error("Failed to fetch cost allocation:", e)
		rows.value = []
	} finally {
		loading.value = false
	}
}

watch(() => [props.fromDate, props.toDate, axis.value], fetchReport)
onMounted(fetchReport)
</script>
