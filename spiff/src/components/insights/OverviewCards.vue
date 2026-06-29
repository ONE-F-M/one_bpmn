<template>
	<div class="grid grid-cols-2 lg:grid-cols-3 xl:grid-cols-6 gap-4">
		<div
			v-for="card in cards"
			:key="card.key"
			class="bg-white rounded-lg shadow-sm p-4 border-l-4"
			:class="card.borderColor"
		>
			<div v-if="loading" class="space-y-3 animate-pulse">
				<div class="h-3 bg-gray-200 rounded w-20"></div>
				<div class="h-7 bg-gray-200 rounded w-16"></div>
			</div>
			<template v-else>
				<div class="flex items-center justify-between mb-2">
					<span class="text-xs text-gray-500 uppercase tracking-wide font-medium">{{ card.title }}</span>
					<Icon :icon="card.icon" class="w-4 h-4 text-gray-400" />
				</div>
				<div class="text-2xl font-bold text-gray-900">{{ card.formattedValue }}</div>
			</template>
		</div>
	</div>
</template>

<script setup>
import { ref, computed, onMounted } from "vue"
import { frappeRequest } from "frappe-ui"
import { Icon } from "@iconify/vue"

const loading = ref(true)
const data = ref({})

const fmt = new Intl.NumberFormat("en-US")
const fmtCurrency = new Intl.NumberFormat("en-US", {
	style: "currency",
	currency: "USD",
	minimumFractionDigits: 2,
	maximumFractionDigits: 4,
})

const cards = computed(() => {
	const d = data.value
	const rate = d.success_rate ?? 0

	return [
		{
			key: "runs_today",
			title: "Runs Today",
			icon: "lucide:play",
			borderColor: "border-blue-500",
			formattedValue: fmt.format(d.runs_today ?? 0),
		},
		{
			key: "success_rate",
			title: "Success Rate",
			icon: "lucide:check-circle",
			borderColor: rate >= 95 ? "border-green-500" : rate >= 85 ? "border-yellow-500" : "border-red-500",
			formattedValue: (d.success_rate ?? 0).toFixed(1) + "%",
		},
		{
			key: "total_cost",
			title: "Cost (7d)",
			icon: "lucide:credit-card",
			borderColor: "border-purple-500",
			formattedValue: fmtCurrency.format(d.total_cost ?? 0),
		},
		{
			key: "active_errors",
			title: "Errors Today",
			icon: "lucide:alert-triangle",
			borderColor: (d.active_errors ?? 0) > 0 ? "border-red-500" : "border-gray-300",
			formattedValue: fmt.format(d.active_errors ?? 0),
		},
		{
			key: "avg_latency_ms",
			title: "Avg Latency",
			icon: "lucide:timer",
			borderColor: "border-amber-500",
			formattedValue: fmt.format(d.avg_latency_ms ?? 0) + "ms",
		},
		{
			key: "total_tokens",
			title: "Tokens (7d)",
			icon: "lucide:hash",
			borderColor: "border-cyan-500",
			formattedValue: fmt.format(d.total_tokens ?? 0),
		},
	]
})

async function fetchOverview() {
	loading.value = true
	try {
		const response = await frappeRequest({
			url: "/api/method/one_bpmn.api.insights_api.get_agent_overview",
			method: "POST",
			params: { days: 7 },
		})
		data.value = response || {}
	} catch (error) {
		console.error("Failed to fetch overview:", error)
		data.value = {}
	} finally {
		loading.value = false
	}
}

onMounted(fetchOverview)
</script>
