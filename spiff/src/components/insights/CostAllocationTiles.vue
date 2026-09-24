<template>
	<div class="space-y-3">
		<div class="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-6 gap-px bg-gray-200 border border-gray-200 rounded-lg overflow-hidden">
			<MetricTile
				v-for="tile in tiles"
				:key="tile.label"
				:label="tile.label"
				:value="tile.value"
				:value-title="tile.valueTitle"
				:delta="tile.delta"
				:good-direction="tile.goodDirection"
				:subtitle="tile.subtitle"
				:subtitle-short="tile.subtitleShort"
			/>
		</div>

		<!-- What this axis leaves out, so the tiles are never read as the whole period. -->
		<div
			v-if="showsScope"
			class="text-sm text-gray-500"
		>
			{{ scope.runs }}:
			<span
				class="font-medium text-gray-700"
				:title="fmtCurrencyExact(totals.cost)"
			>{{ fmtCurrency(totals.cost) }}</span>
			of {{ fmtCurrency(periodCost) }} total AI spend this period.
			<template v-if="totals.other_axis_cost">
				{{ scope.otherRuns }} {{ fmtCurrency(totals.other_axis_cost) }} are allocated under
				<button
					class="underline hover:text-gray-700"
					@click="emit('switch-axis')"
				>
					{{ scope.otherAxis }}</button>.
			</template>
		</div>
	</div>
</template>

<script setup>
import { computed } from "vue"
import MetricTile from "@/components/insights/MetricTile.vue"
import { fmtCompact, fmtCurrency, fmtCurrencyExact, fmtDateRange, fmtInt } from "@/utils/formatters"
import { pctChange } from "@/utils/costAllocation"

const props = defineProps({
	report: { type: Object, required: true },
})
const emit = defineEmits(["switch-axis"])

const isChat = computed(() => props.report.axis === "chat_user")
const totals = computed(() => props.report.totals)
const previous = computed(() => props.report.previous)
const periodCost = computed(() => props.report.period_totals.cost)
const showsScope = computed(() => totals.value.cost !== periodCost.value)
const priorDates = computed(() => fmtDateRange(previous.value.from_date, previous.value.to_date))
const scope = computed(() =>
	isChat.value
		? { runs: "Chat runs", otherRuns: "Process runs", otherAxis: "By process owner" }
		: { runs: "Process runs", otherRuns: "Chat runs", otherAxis: "By chat user" }
)

const tiles = computed(() => {
	const t = totals.value
	const p = previous.value
	const avgBefore = p.runs ? p.cost / p.runs : 0
	const vs = { subtitle: `vs ${priorDates.value}`, subtitleShort: priorDates.value }
	return [
		{
			label: isChat.value ? "Chat spend" : "Process spend",
			value: fmtCurrency(t.cost),
			valueTitle: fmtCurrencyExact(t.cost),
			delta: pctChange(t.cost, p.cost),
			goodDirection: "down",
			...vs,
		},
		{ label: "Runs", value: fmtInt(t.runs), delta: pctChange(t.runs, p.runs), goodDirection: "up", ...vs },
		{
			label: "Tokens",
			value: fmtCompact(t.tokens),
			valueTitle: fmtInt(t.tokens),
			delta: pctChange(t.tokens, p.tokens),
			goodDirection: "up",
			...vs,
		},
		{
			label: "Avg cost / run",
			value: fmtCurrency(t.avg_cost_per_run),
			valueTitle: fmtCurrencyExact(t.avg_cost_per_run),
			delta: pctChange(t.avg_cost_per_run, avgBefore),
			goodDirection: "down",
			...vs,
		},
		{
			label: "Departments",
			value: fmtInt(t.departments),
			subtitle: isChat.value ? `${fmtInt(t.active_users)} of ${fmtInt(t.seats)} seats active` : `${fmtInt(t.people)} process owners`,
		},
		isChat.value
			? { label: "Conversations", value: fmtInt(t.conversations), subtitle: `${fmtCurrency(t.avg_cost_per_conversation)} each` }
			: { label: "Processes", value: fmtInt(t.processes), subtitle: t.top_process ? `Top: ${t.top_process}` : "" },
	]
})
</script>

<style scoped></style>
