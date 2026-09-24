<template>
	<div class="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-6 gap-px bg-gray-200 border border-gray-200 rounded-lg overflow-hidden">
		<ErrorMessage
			v-if="error"
			class="col-span-full bg-white p-4"
			:message="error"
		/>
		<template v-else>
			<MetricTile
				v-for="card in cards"
				:key="card.key"
				:label="card.title"
				:value="card.formattedValue"
				:value-title="card.valueTitle"
				:delta="loading ? undefined : (data.delta?.[card.key] ?? null)"
				:delta-kind="card.deltaKind"
				:good-direction="card.goodDirection"
				:subtitle="priorText"
				:subtitle-short="priorTextShort"
				:sparkline="data.sparklines?.[card.key]"
				:sparkline-class="card.sparklineClass"
				:loading="loading"
			/>
		</template>
	</div>
</template>

<script setup>
import { ref, computed, watch, onMounted } from "vue"
import { ErrorMessage, frappeRequest } from "frappe-ui"
import { dayjs } from "@/dayjs"
import MetricTile from "@/components/insights/MetricTile.vue"
import { fmtInt, fmtCurrency, fmtCurrencyExact, fmtPct, fmtCompact } from "@/utils/formatters"

const props = defineProps({
	fromDate: { type: String, default: "" },
	toDate: { type: String, default: "" },
	origin: { type: String, default: "production" },
	model: { type: String, default: "" },
	provider: { type: String, default: "" },
	processModel: { type: String, default: "" },
})

const __ = (window.__ && typeof window.__ === "function") ? window.__ : (s) => s

const loading = ref(true)
const error = ref(null)
const data = ref({})

const rangeDays = computed(() => dayjs(props.toDate).diff(dayjs(props.fromDate), "day") + 1)
const priorText = computed(() =>
	rangeDays.value === 1 ? __("vs prior 1 day") : `${__("vs prior")} ${rangeDays.value} ${__("days")}`,
)
const priorTextShort = computed(() => `${__("vs prior")} ${rangeDays.value}d`)

const cards = computed(() => {
	const current = data.value.current || {}

	return [
		{
			key: "cost",
			title: __("Cost"),
			formattedValue: fmtCurrency(current.cost),
			valueTitle: fmtCurrencyExact(current.cost),
			deltaKind: "pct",
			goodDirection: "down",
		},
		{
			key: "tokens",
			title: __("Tokens"),
			formattedValue: fmtCompact(current.tokens),
			valueTitle: fmtInt(current.tokens),
			deltaKind: "pct",
			goodDirection: "down",
		},
		{
			key: "runs",
			title: __("Runs"),
			formattedValue: fmtInt(current.runs),
			valueTitle: String(current.runs ?? 0),
			deltaKind: "pct",
			goodDirection: "up",
		},
		{
			key: "avg_cost",
			title: __("Avg cost / run"),
			formattedValue: fmtCurrency(current.avg_cost),
			valueTitle: fmtCurrencyExact(current.avg_cost),
			deltaKind: "pct",
			goodDirection: "down",
		},
		{
			key: "success_rate",
			title: __("Success rate"),
			formattedValue: fmtPct(current.success_rate),
			valueTitle: String(current.success_rate ?? 0),
			deltaKind: "pt",
			goodDirection: "up",
			sparklineClass: "text-green-500",
		},
		{
			key: "cache_hit_rate",
			title: __("Cache hit rate"),
			formattedValue: fmtPct(current.cache_hit_rate),
			valueTitle: String(current.cache_hit_rate ?? 0),
			deltaKind: "pt",
			goodDirection: "up",
			sparklineClass: "text-cyan-500",
		},
	]
})

async function fetchOverview() {
	loading.value = true
	error.value = null
	try {
		const response = await frappeRequest({
			url: "/api/method/one_bpmn.api.insights_api.get_agent_overview",
			method: "POST",
			params: {
				from_date: props.fromDate,
				to_date: props.toDate,
				origin: props.origin,
				model: props.model,
				provider: props.provider,
				process_model: props.processModel,
			},
		})
		data.value = response || {}
	} catch (err) {
		error.value = err
		data.value = {}
	} finally {
		loading.value = false
	}
}

watch(() => [props.fromDate, props.toDate, props.origin, props.model, props.provider, props.processModel], fetchOverview)
onMounted(fetchOverview)
</script>
