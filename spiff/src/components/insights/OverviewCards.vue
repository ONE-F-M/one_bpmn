<template>
	<div class="grid grid-cols-2 lg:grid-cols-3 xl:grid-cols-6 gap-4">
		<MetricTile
			v-for="card in cards"
			:key="card.key"
			:label="card.title"
			:value="card.formattedValue"
			:value-title="card.valueTitle"
			:delta="card.delta"
			:delta-kind="card.deltaKind"
			:good-direction="card.goodDirection"
			:loading="loading"
		/>
	</div>
</template>

<script setup>
import { ref, computed, watch, onMounted } from "vue"
import { frappeRequest } from "frappe-ui"
import MetricTile from "@/components/insights/MetricTile.vue"
import { fmtInt, fmtCurrency, fmtCurrencyExact, fmtPct, fmtCompact, fmtDuration } from "@/utils/formatters"

const props = defineProps({
	origin: { type: String, default: "production" },
})

const loading = ref(true)
const data = ref({})

// No prior-period comparison is wired up yet, so every tile shows "new"
// via MetricTile's null-delta state until the API returns one.
const cards = computed(() => {
	const d = data.value

	return [
		{
			key: "runs_today",
			title: "Runs Today",
			formattedValue: fmtInt(d.runs_today),
			delta: null,
			deltaKind: "pct",
			goodDirection: "up",
		},
		{
			key: "success_rate",
			title: "Success Rate",
			formattedValue: fmtPct(d.success_rate),
			delta: null,
			deltaKind: "pt",
			goodDirection: "up",
		},
		{
			key: "total_cost",
			title: "Cost (7d)",
			formattedValue: fmtCurrency(d.total_cost),
			valueTitle: fmtCurrencyExact(d.total_cost),
			delta: null,
			deltaKind: "pct",
			goodDirection: "down",
		},
		{
			key: "active_errors",
			title: "Errors Today",
			formattedValue: fmtInt(d.active_errors),
			delta: null,
			deltaKind: "pct",
			goodDirection: "down",
		},
		{
			key: "avg_latency_ms",
			title: "Avg Latency",
			formattedValue: fmtDuration(d.avg_latency_ms),
			delta: null,
			deltaKind: "pct",
			goodDirection: "down",
		},
		{
			key: "total_tokens",
			title: "Tokens (7d)",
			formattedValue: fmtCompact(d.total_tokens),
			valueTitle: fmtInt(d.total_tokens),
			delta: null,
			deltaKind: "pct",
			goodDirection: "up",
		},
	]
})

async function fetchOverview() {
	loading.value = true
	try {
		const response = await frappeRequest({
			url: "/api/method/one_bpmn.api.insights_api.get_agent_overview",
			method: "POST",
			params: { days: 7, origin: props.origin },
		})
		data.value = response || {}
	} catch (error) {
		console.error("Failed to fetch overview:", error)
		data.value = {}
	} finally {
		loading.value = false
	}
}

watch(() => props.origin, fetchOverview)
onMounted(fetchOverview)
</script>
