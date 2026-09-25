<template>
	<div class="divide-y divide-gray-100 border-t border-gray-200">
		<div
			v-for="row in rows"
			:key="row.path"
			class="py-3 pr-1"
			:style="indentOf(row, 16)"
		>
			<div
				class="flex items-center gap-2 w-full text-left"
				:role="row.hasChildren ? 'button' : undefined"
				:tabindex="row.hasChildren ? 0 : undefined"
				:aria-expanded="expandedOf(row)"
				@click="onCardClick(row)"
				@keydown.enter.space.prevent="onCardClick(row)"
			>
				<Icon
					v-if="row.hasChildren"
					:icon="chevronOf(row)"
					class="w-4 h-4 text-gray-400 shrink-0"
				/>
				<span
					v-else
					class="w-4 shrink-0"
				></span>
				<span
					v-if="row.depth === 0"
					class="w-2 h-2 rounded-full shrink-0"
					:style="{ background: colors[row.node.key] }"
				></span>
				<span
					class="text-sm text-gray-900 truncate flex-1"
					:class="{ 'font-medium': row.depth === 0 }"
				>{{ nameOf(row.node) }}</span>
				<span
					class="text-sm text-gray-900 whitespace-nowrap"
					:class="{ 'font-medium': row.depth === 0 }"
					:title="fmtCurrencyExact(row.node.cost)"
				>{{ fmtCurrency(row.node.cost) }}</span>
			</div>
			<div
				v-if="row.depth === 0"
				class="flex items-center gap-2 pl-6 mt-1.5"
			>
				<ShareBar
					class="flex-1"
					:share="barWidth(row.node, tree)"
					:color="colors[row.node.key]"
				/>
				<span class="text-xs text-gray-500 w-8 text-right">{{ fmtPct(row.node.share, 0) }}</span>
				<DeltaPill
					:delta="row.node.delta"
					good-direction="down"
				/>
			</div>
			<div
				v-else-if="showsShareLine(row)"
				class="pl-6 mt-0.5 text-xs text-gray-500"
			>
				{{ shareLine(row) }}
			</div>
		</div>
		<div class="py-3 flex items-start justify-between gap-3">
			<div>
				<div class="text-sm font-medium text-gray-900">{{ totalLabel(axis) }}</div>
				<div class="text-xs text-gray-500 mt-1">{{ totalLine }}</div>
				<div class="flex items-center gap-1.5 mt-1 text-xs text-gray-500">
					<DeltaPill
						:delta="costDelta"
						good-direction="down"
					/>
					<span>{{ priorLabel }}</span>
				</div>
			</div>
			<span
				class="text-sm font-bold text-gray-900 whitespace-nowrap"
				:title="fmtCurrencyExact(totals.cost)"
			>{{ fmtCurrency(totals.cost) }}</span>
		</div>
	</div>
</template>

<script setup>
import { computed } from "vue"
import { Icon } from "@iconify/vue"
import DeltaPill from "@/components/insights/DeltaPill.vue"
import ShareBar from "@/components/insights/ShareBar.vue"
import { fmtCompact, fmtCurrency, fmtCurrencyExact, fmtDateRange, fmtInt, fmtPct } from "@/utils/formatters"
import { barWidth, chevronOf, indentOf, nameOf, totalLabel } from "@/utils/costAllocation"

const props = defineProps({
	report: { type: Object, required: true },
	rows: { type: Array, required: true },
	colors: { type: Object, required: true },
	costDelta: { type: Number, default: null },
})
const emit = defineEmits(["toggle"])

const axis = computed(() => props.report.axis)
const tree = computed(() => props.report.tree)
const totals = computed(() => props.report.totals)
const previous = computed(() => props.report.previous)
const priorLabel = computed(() => fmtDateRange(previous.value.from_date, previous.value.to_date))
const totalLine = computed(() => `${fmtInt(totals.value.runs)} runs · ${fmtCompact(totals.value.tokens)} tokens`)

function expandedOf(row) {
	return row.hasChildren ? row.open : undefined
}
function onCardClick(row) {
	if (row.hasChildren) emit("toggle", row.path)
}
function showsShareLine(row) {
	return row.depth === 1 && row.node.kind !== "more"
}
function shareLine(row) {
	return `${fmtPct(row.node.share, 0)} of ${axis.value === "chat_user" ? "chat" : "process"} spend`
}
</script>

<style scoped></style>
