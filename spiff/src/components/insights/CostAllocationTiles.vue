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
				:delta-kind="tile.deltaKind"
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
			<template v-if="isChat">
				Top 5 users account for
				<span class="font-medium text-gray-700">{{ fmtPct(totals.top5_share, 0) }}</span>
				of chat spend.
			</template>
		</div>
	</div>
</template>

<script setup>
import { computed } from "vue"
import MetricTile from "@/components/insights/MetricTile.vue"
import { useWindowSize } from "@/composables/useWindowSize"
import { fmtCompact, fmtCurrency, fmtCurrencyExact, fmtDateRange, fmtInt, fmtPct } from "@/utils/formatters"
import { pctChange } from "@/utils/costAllocation"

const props = defineProps({
	report: { type: Object, required: true },
})
const emit = defineEmits(["switch-axis"])

const { isMobile } = useWindowSize()
const isChat = computed(() => props.report.axis === "chat_user")
const totals = computed(() => props.report.totals)
const previous = computed(() => props.report.previous)
const periodCost = computed(() => props.report.period_totals.cost)
const showsScope = computed(() => totals.value.cost !== periodCost.value)
const priorDates = computed(() => fmtDateRange(previous.value.from_date, previous.value.to_date))
const vsPrior = computed(() => ({ subtitle: `vs ${priorDates.value}`, subtitleShort: priorDates.value }))
const scope = computed(() =>
	isChat.value
		? { runs: "Chat runs", otherRuns: "Process runs", otherAxis: "By process owner" }
		: { runs: "Process runs", otherRuns: "Chat runs", otherAxis: "By chat user" }
)

function money(label, value, delta) {
	return { label, value: fmtCurrency(value), valueTitle: fmtCurrencyExact(value), delta, goodDirection: "down", ...vsPrior.value }
}

const chatTiles = computed(() => {
	const t = totals.value
	const p = previous.value
	return [
		money("Chat spend", t.cost, pctChange(t.cost, p.cost)),
		{
			label: "Conversations",
			value: fmtInt(t.conversations),
			delta: pctChange(t.conversations, p.conversations),
			goodDirection: "up",
			...vsPrior.value,
		},
		{
			label: "Active users",
			value: fmtInt(t.active_users),
			delta: t.active_users - p.users,
			deltaKind: "count",
			goodDirection: "up",
			subtitle: `of ${fmtInt(t.seats)} seats`,
		},
		money("Avg cost / user", t.avg_cost_per_user, pctChange(t.avg_cost_per_user, p.avg_cost_per_user)),
		money(
			isMobile.value ? "Avg cost / conv" : "Avg cost / conversation",
			t.avg_cost_per_conversation,
			pctChange(t.avg_cost_per_conversation, p.avg_cost_per_conversation),
		),
		{
			label: "Departments",
			value: fmtInt(t.departments),
			subtitle: `Top: ${t.top_department.name} ${fmtPct(t.top_department.share, 0)}`,
		},
	]
})

const processTiles = computed(() => {
	const t = totals.value
	const p = previous.value
	return [
		money("Process spend", t.cost, pctChange(t.cost, p.cost)),
		{ label: "Runs", value: fmtInt(t.runs), delta: pctChange(t.runs, p.runs), goodDirection: "up", ...vsPrior.value },
		{
			label: "Tokens",
			value: fmtCompact(t.tokens),
			valueTitle: fmtInt(t.tokens),
			delta: pctChange(t.tokens, p.tokens),
			goodDirection: "up",
			...vsPrior.value,
		},
		money("Avg cost / run", t.avg_cost_per_run, pctChange(t.avg_cost_per_run, p.avg_cost_per_run)),
		{ label: "Departments", value: fmtInt(t.departments), subtitle: `${fmtInt(t.people)} process owners` },
		{ label: "Processes", value: fmtInt(t.processes), subtitle: t.top_process ? `Top: ${t.top_process}` : "" },
	]
})

const tiles = computed(() => (isChat.value ? chatTiles.value : processTiles.value))
</script>

<style scoped></style>
