<template>
	<div class="divide-y divide-gray-100 border-t border-gray-200">
		<div
			v-for="row in rows"
			:key="row.path"
			class="py-3 pr-1"
			:style="indentOf(row, 16)"
		>
			<div class="flex items-center gap-2">
				<button
					v-if="row.hasChildren"
					class="text-gray-400 p-1 -m-1"
					:aria-expanded="row.open"
					:aria-label="toggleLabelOf(row)"
					@click="emit('toggle', row.path)"
				>
					<Icon
						:icon="chevronOf(row)"
						class="w-4 h-4"
					/>
				</button>
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
				>
					{{ row.node.label }}
				</span>
				<span
					class="text-sm text-gray-900 font-medium"
					:title="fmtCurrencyExact(row.node.cost)"
				>{{ fmtCurrency(row.node.cost) }}</span>
			</div>
			<div class="flex items-center gap-2 pl-6 mt-1 text-xs text-gray-500">
				<span>{{ fmtPct(row.node.share, 0) }}</span>
				<DeltaPill
					:delta="row.node.delta"
					good-direction="down"
				/>
				<span v-if="row.node.delta !== null">vs prior</span>
				<span
					v-if="subtitleOf(row.node, axis)"
					class="truncate"
				>· {{ subtitleOf(row.node, axis) }}</span>
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
				class="text-sm font-bold text-gray-900"
				:title="fmtCurrencyExact(totals.cost)"
			>{{ fmtCurrency(totals.cost) }}</span>
		</div>
	</div>
</template>

<script setup>
import { computed } from "vue"
import { Icon } from "@iconify/vue"
import DeltaPill from "@/components/insights/DeltaPill.vue"
import { fmtCompact, fmtCurrency, fmtCurrencyExact, fmtDateRange, fmtInt, fmtPct } from "@/utils/formatters"
import { chevronOf, indentOf, subtitleOf, toggleLabelOf, totalLabel } from "@/utils/costAllocation"

const props = defineProps({
	report: { type: Object, required: true },
	rows: { type: Array, required: true },
	colors: { type: Object, required: true },
	costDelta: { type: Number, default: null },
})
const emit = defineEmits(["toggle"])

const axis = computed(() => props.report.axis)
const totals = computed(() => props.report.totals)
const previous = computed(() => props.report.previous)
const priorLabel = computed(() => fmtDateRange(previous.value.from_date, previous.value.to_date))
const totalLine = computed(() => `${fmtInt(totals.value.runs)} runs · ${fmtCompact(totals.value.tokens)} tokens`)
</script>

<style scoped></style>
