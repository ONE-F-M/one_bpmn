<template>
	<div class="overflow-x-auto">
		<table class="w-full">
			<thead>
				<tr class="border-b border-gray-200">
					<th class="text-left text-xs uppercase text-gray-500 font-medium py-2 px-3">
						{{ levelHeader }}
					</th>
					<th class="text-right text-xs uppercase text-gray-500 font-medium py-2 px-3">Runs</th>
					<th class="text-right text-xs uppercase text-gray-500 font-medium py-2 px-3">Tokens</th>
					<th
						v-for="m in months"
						:key="m"
						class="text-right text-xs uppercase text-gray-500 font-medium py-2 px-3 whitespace-nowrap"
					>
						{{ monthHeader(m) }}
					</th>
					<th class="text-right text-xs uppercase text-gray-500 font-medium py-2 px-3">
						<span class="inline-flex items-center gap-1">
							Cost
							<Icon
								icon="lucide:arrow-down"
								class="w-3 h-3"
							/>
						</span>
					</th>
					<th class="text-left text-xs uppercase text-gray-500 font-medium py-2 px-3 w-40">Share</th>
					<th class="text-right text-xs uppercase text-gray-500 font-medium py-2 px-3">Vs prior</th>
				</tr>
			</thead>
			<tbody>
				<tr
					v-for="row in rows"
					:key="row.path"
					class="border-b border-gray-100 hover:bg-gray-50"
					:class="{ 'cursor-pointer': row.hasChildren }"
					@click="onRowClick(row)"
				>
					<td class="py-2.5 px-3 text-sm text-gray-900">
						<div
							class="flex items-center gap-2"
							:style="indentOf(row, 20)"
						>
							<button
								v-if="row.hasChildren"
								class="text-gray-400 hover:text-gray-600 shrink-0"
								:aria-expanded="row.open"
								:aria-label="toggleLabelOf(row)"
								@click.stop="emit('toggle', row.path)"
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
							<Avatar
								v-if="isPerson(row.node)"
								size="sm"
								:label="nameOf(row.node)"
							/>
							<span
								class="truncate"
								:class="{ 'font-medium': row.depth === 0 }"
							>{{ nameOf(row.node) }}</span>
							<span
								v-if="row.node.name"
								class="text-xs text-gray-500 truncate hidden md:inline"
							>{{ row.node.label }}</span>
							<Badge
								v-if="chipOf(row)"
								size="sm"
								:label="chipOf(row)"
							/>
						</div>
					</td>
					<td class="py-2.5 px-3 text-sm text-gray-600 text-right">{{ fmtInt(row.node.runs) }}</td>
					<td
						class="py-2.5 px-3 text-sm text-gray-600 text-right"
						:title="fmtInt(row.node.tokens)"
					>
						{{ fmtCompact(row.node.tokens) }}
					</td>
					<td
						v-for="m in months"
						:key="m"
						class="py-2.5 px-3 text-sm text-gray-600 text-right"
					>
						{{ monthCost(row.node, m) }}
					</td>
					<td
						class="py-2.5 px-3 text-sm text-gray-900 text-right font-medium"
						:title="fmtCurrencyExact(row.node.cost)"
					>
						{{ fmtCurrency(row.node.cost) }}
					</td>
					<td class="py-2.5 px-3">
						<div class="flex items-center gap-2">
							<ShareBar
								class="flex-1"
								:share="barWidth(row.node, tree)"
								:color="colors[row.rootKey]"
							/>
							<span class="text-xs text-gray-500 w-10 text-right">{{ fmtPct(row.node.share, 0) }}</span>
						</div>
					</td>
					<td class="py-2.5 px-3 text-right">
						<DeltaPill
							:delta="row.node.delta"
							good-direction="down"
						/>
					</td>
				</tr>
			</tbody>
			<tfoot>
				<tr class="border-t-2 border-gray-200">
					<td class="py-2.5 px-3 text-xs uppercase text-gray-500 font-medium">{{ totalLabel(axis) }}</td>
					<td class="py-2.5 px-3 text-sm text-gray-900 text-right font-bold">{{ fmtInt(totals.runs) }}</td>
					<td
						class="py-2.5 px-3 text-sm text-gray-900 text-right font-bold"
						:title="fmtInt(totals.tokens)"
					>
						{{ fmtCompact(totals.tokens) }}
					</td>
					<td
						v-for="m in months"
						:key="m"
						class="py-2.5 px-3 text-sm text-gray-900 text-right font-bold"
					>
						{{ fmtCurrency(monthTotal(m)) }}
					</td>
					<td
						class="py-2.5 px-3 text-sm text-gray-900 text-right font-bold"
						:title="fmtCurrencyExact(totals.cost)"
					>
						{{ fmtCurrency(totals.cost) }}
					</td>
					<td class="py-2.5 px-3 text-xs text-gray-500">100%</td>
					<td class="py-2.5 px-3 text-right">
						<DeltaPill
							:delta="costDelta"
							good-direction="down"
						/>
					</td>
				</tr>
			</tfoot>
		</table>
	</div>
</template>

<script setup>
import { computed } from "vue"
import { Avatar, Badge } from "frappe-ui"
import { Icon } from "@iconify/vue"
import { dayjs } from "@/dayjs"
import DeltaPill from "@/components/insights/DeltaPill.vue"
import ShareBar from "@/components/insights/ShareBar.vue"
import { fmtCompact, fmtCurrency, fmtCurrencyExact, fmtInt, fmtPct } from "@/utils/formatters"
import {
	barWidth, chevronOf, indentOf, monthColumns, nameOf, subtitleOf, toggleLabelOf, totalLabel,
} from "@/utils/costAllocation"

const props = defineProps({
	report: { type: Object, required: true },
	rows: { type: Array, required: true },
	colors: { type: Object, required: true },
	levelHeader: { type: String, required: true },
	costDelta: { type: Number, default: null },
})
const emit = defineEmits(["toggle"])

const axis = computed(() => props.report.axis)
const tree = computed(() => props.report.tree)
const totals = computed(() => props.report.totals)
const months = computed(() => monthColumns(props.report.months))

function onRowClick(row) {
	if (row.hasChildren) emit("toggle", row.path)
}
function isPerson(node) {
	return node.kind === "owner" || node.kind === "user"
}
function chipOf(row) {
	if (row.node.kind === "department" || row.node.kind === "more") return subtitleOf(row.node, axis.value)
	return row.depth === 0 ? row.node.department : ""
}
function monthHeader(m) {
	const label = dayjs(`${m}-01`).format("MMM YYYY")
	return m === dayjs().format("YYYY-MM") ? `${label} (to date)` : label
}
function monthCost(node, m) {
	return node.by_month[m] ? fmtCurrency(node.by_month[m]) : ""
}
function monthTotal(m) {
	return tree.value.reduce((t, n) => t + n.by_month[m], 0)
}
</script>

<style scoped></style>
