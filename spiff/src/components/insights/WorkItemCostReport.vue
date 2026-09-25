<template>
	<div class="space-y-6">
		<!-- Work Item picker -->
		<div class="flex flex-wrap gap-3 items-center">
			<div class="w-80">
				<Autocomplete
					v-model="selectedWorkItem"
					:options="workItemOptions"
					:loading="searching"
					:compare-fn="compareOption"
					placeholder="Search Orchestrator Work Items…"
					@update:query="debouncedSearch"
				/>
			</div>
		</div>

		<!-- Nothing selected yet -->
		<div v-if="!selectedWorkItem" class="flex flex-col items-center justify-center h-48 text-center">
			<Icon icon="lucide:search" class="w-12 h-12 text-gray-300 mb-3" />
			<h3 class="text-base font-medium text-gray-900">Pick a Work Item</h3>
			<p class="text-sm text-gray-500">
				Search above to see its AI cost breakdown. Only Work Items with
				<span class="font-medium">Orchestrator</span> ticked are listed.
			</p>
		</div>

		<!-- Loading -->
		<div v-else-if="loading" class="flex items-center justify-center h-48 text-gray-500">Loading…</div>

		<template v-else>
			<!-- Depth cap warning: the total may be a floor, not the whole figure. -->
			<div
				v-if="report.chain_truncated"
				class="bg-amber-50 text-amber-800 text-sm rounded-lg px-4 py-3"
			>
				<span class="font-medium">This total may be incomplete.</span>
				The delegation chain for this Work Item is deeper than this report walks,
				so the figures below are a floor, not the whole cost.
			</div>

			<!-- Summary tiles -->
			<div class="grid grid-cols-2 lg:grid-cols-3 gap-4">
				<div class="bg-white rounded-lg shadow-sm p-4 border-l-4 border-purple-500">
					<div class="text-xs text-gray-500 uppercase tracking-wide font-medium">Total Cost</div>
					<div
						class="text-2xl font-bold text-gray-900"
						:title="fmtCurrencyExact(report.total_cost)"
					>
						{{ fmtCost(report.total_cost) }}
					</div>
				</div>
				<div class="bg-white rounded-lg shadow-sm p-4 border-l-4 border-amber-500">
					<div class="text-xs text-gray-500 uppercase tracking-wide font-medium">Total Tokens</div>
					<div
						class="text-2xl font-bold text-gray-900"
						:title="fmtNum(report.total_tokens)"
					>
						{{ fmtCompact(report.total_tokens) }}
					</div>
				</div>
				<div class="bg-white rounded-lg shadow-sm p-4 border-l-4 border-blue-500">
					<div class="text-xs text-gray-500 uppercase tracking-wide font-medium">Runs</div>
					<div class="text-2xl font-bold text-gray-900">{{ fmtNum(report.breakdown.length) }}</div>
				</div>
			</div>

			<!-- Empty state: a real work item with no contributing runs, not an error. -->
			<div
				v-if="!report.breakdown.length"
				class="flex flex-col items-center justify-center h-48 text-center"
			>
				<Icon icon="lucide:receipt" class="w-12 h-12 text-gray-300 mb-3" />
				<h3 class="text-base font-medium text-gray-900">No AI runs for this Work Item</h3>
				<p class="text-sm text-gray-500">Nothing has been delegated to an agent for it yet.</p>
			</div>

			<!-- Runs table -->
			<div v-else class="overflow-x-auto">
				<table class="w-full">
					<thead>
						<tr class="border-b border-gray-200">
							<th class="text-left text-xs uppercase text-gray-500 font-medium py-2 px-3">Agent</th>
							<th class="text-left text-xs uppercase text-gray-500 font-medium py-2 px-3">Model</th>
							<th class="text-right text-xs uppercase text-gray-500 font-medium py-2 px-3">Tokens</th>
							<th class="text-right text-xs uppercase text-gray-500 font-medium py-2 px-3">Cost</th>
						</tr>
					</thead>
					<tbody>
						<tr
							v-for="r in report.breakdown"
							:key="r.run"
							class="border-b border-gray-100 hover:bg-gray-50"
						>
							<td class="py-2.5 px-3 text-sm text-gray-900 font-medium">{{ r.agent_configuration || "—" }}</td>
							<td class="py-2.5 px-3 text-sm text-gray-600">{{ r.model || "—" }}</td>
							<td
								class="py-2.5 px-3 text-sm text-gray-600 text-right"
								:title="fmtNum(r.tokens)"
							>
								{{ fmtCompact(r.tokens) }}
							</td>
							<td
								class="py-2.5 px-3 text-sm text-gray-900 text-right font-medium"
								:title="fmtCurrencyExact(r.cost)"
							>
								{{ fmtCost(r.cost) }}
							</td>
						</tr>
					</tbody>
					<tfoot>
						<tr class="border-t-2 border-gray-200">
							<td colspan="2" class="py-2.5 px-3 text-xs uppercase text-gray-500 font-medium">Total</td>
							<td
								class="py-2.5 px-3 text-sm text-gray-900 text-right font-bold"
								:title="fmtNum(report.total_tokens)"
							>
								{{ fmtCompact(report.total_tokens) }}
							</td>
							<td
								class="py-2.5 px-3 text-sm text-gray-900 text-right font-bold"
								:title="fmtCurrencyExact(report.total_cost)"
							>
								{{ fmtCost(report.total_cost) }}
							</td>
						</tr>
					</tfoot>
				</table>
			</div>
		</template>
	</div>
</template>

<script setup>
import { ref, watch } from "vue"
import { frappeRequest, Autocomplete } from "frappe-ui"
import { Icon } from "@iconify/vue"
import { fmtInt as fmtNum, fmtCompact, fmtCurrency as fmtCost, fmtCurrencyExact } from "@/utils/formatters"

const searching = ref(false)
const workItemOptions = ref([])
const selectedWorkItem = ref(null)
let searchTimer = null

const loading = ref(false)
const report = ref({ total_cost: 0, total_tokens: 0, breakdown: [], chain_truncated: false })

// frappe-ui's default comparator is `(a, b) => a.value === b.value`, which
// throws the moment either side is null — the same trap UserFilter and
// Evals.vue guard against for their own Autocompletes.
function compareOption(a, b) {
	return a?.value === b?.value
}

function debouncedSearch(query) {
	clearTimeout(searchTimer)
	searchTimer = setTimeout(() => searchWorkItems(query), 300)
}

async function searchWorkItems(query = "") {
	searching.value = true
	try {
		const result = await frappeRequest({
			url: "/api/method/one_bpmn.api.insights_api.search_orchestrator_work_items",
			method: "POST",
			params: { query },
		})
		workItemOptions.value = (result || []).map((w) => ({
			label: w.title ? `${w.name} — ${w.title}` : w.name,
			value: w.name,
		}))
	} catch (e) {
		console.error("Failed to search work items:", e)
		workItemOptions.value = []
	} finally {
		searching.value = false
	}
}

async function fetchReport(workItemName) {
	if (!workItemName) {
		report.value = { total_cost: 0, total_tokens: 0, breakdown: [], chain_truncated: false }
		return
	}
	loading.value = true
	try {
		const res = await frappeRequest({
			url: "/api/method/one_bpmn.api.insights_api.get_work_item_delegation_cost",
			method: "POST",
			params: { work_item_name: workItemName },
		})
		report.value = {
			total_cost: res?.total_cost || 0,
			total_tokens: res?.total_tokens || 0,
			breakdown: res?.breakdown || [],
			chain_truncated: !!res?.chain_truncated,
		}
	} catch (e) {
		console.error("Failed to fetch work item cost:", e)
		report.value = { total_cost: 0, total_tokens: 0, breakdown: [], chain_truncated: false }
	} finally {
		loading.value = false
	}
}

watch(selectedWorkItem, (opt) => fetchReport(opt?.value))

searchWorkItems()
</script>
