<template>
	<div class="overflow-x-auto">
		<div class="min-w-[900px]">
			<ListView
				:columns="columns"
				:rows="sortedRows"
				row-key="key"
				:options="{ selectable: false, showTooltip: false }"
			>
				<ListHeader>
					<ListHeaderItem
						v-for="column in columns"
						:key="column.key"
						:item="column"
						class="cursor-pointer select-none"
						@click="sortBy(column.key)"
					>
						<template #suffix>
							<Icon
								v-if="activeSortKey === column.key"
								:icon="descending ? 'lucide:arrow-down' : 'lucide:arrow-up'"
								class="w-3 h-3"
							/>
						</template>
					</ListHeaderItem>
				</ListHeader>
				<ListRows />
				<ListRow :row="totalRow" />
				<template #cell="{ column, row, item }">
					<div
						class="flex w-full items-center"
						:class="column.align === 'right' ? 'justify-end' : 'justify-start'"
					>
						<span
							v-if="column.key === 'cache_hit_rate' && !row.isTotal"
							class="text-[11px] font-medium rounded px-1.5 py-0.5"
							:class="item >= GOOD_CACHE_HIT_RATE ? 'bg-green-50 text-green-700' : 'text-gray-500'"
						>
							{{ fmtPct(item, 0) }}
						</span>
						<div
							v-else-if="column.key === 'share'"
							class="flex items-center gap-2"
						>
							<ShareBar
								class="w-16"
								:share="item || 0"
								:color="row.isTotal ? 'transparent' : colors[row.name]"
							/>
							<span class="text-sm">{{ fmtPct(item, 0) }}</span>
						</div>
						<DeltaPill
							v-else-if="column.key === 'delta'"
							:delta="item"
							good-direction="down"
						/>
						<span
							v-else
							class="text-sm"
							:class="{ 'font-semibold text-gray-900': row.isTotal }"
							:title="titleFor(column.key, item) || undefined"
						>
							{{ format(column.key, item) }}
						</span>
					</div>
				</template>
			</ListView>
		</div>
	</div>
</template>

<script setup>
import { ref, computed } from "vue"
import { ListHeader, ListHeaderItem, ListRow, ListRows, ListView } from "frappe-ui"
import { Icon } from "@iconify/vue"
import DeltaPill from "@/components/insights/DeltaPill.vue"
import ShareBar from "@/components/insights/ShareBar.vue"
import { fmtCompact, fmtCurrency, fmtCurrencyExact, fmtInt, fmtPct } from "@/utils/formatters"

const props = defineProps({
	series: { type: Array, required: true },
	total: { type: Object, required: true },
	colors: { type: Object, required: true },
	groupBy: { type: String, default: "model" },
})

const __ = (window.__ && typeof window.__ === "function") ? window.__ : (s) => s
const GOOD_CACHE_HIT_RATE = 30
const TOKEN_KEYS = ["input_tokens", "output_tokens"]
const CURRENCY_KEYS = ["cost", "avg_cost"]

const sortKey = ref(null)
const descending = ref(true)

const activeSortKey = computed(() => sortKey.value || "cost")

const columns = computed(() =>
	[
		{ key: "name", label: props.groupBy === "agent" ? __("AI Agent") : __("Model"), width: "14rem" },
		props.groupBy === "agent" ? null : { key: "provider", label: __("Provider"), width: "7rem" },
		{ key: "runs", label: __("Runs"), align: "right" },
		{ key: "input_tokens", label: __("Input tok"), align: "right" },
		{ key: "output_tokens", label: __("Output tok"), align: "right" },
		{ key: "cache_hit_rate", label: __("Cached"), align: "right" },
		{ key: "cost", label: __("Cost"), align: "right" },
		{ key: "avg_cost", label: __("Avg / run"), align: "right" },
		{ key: "share", label: __("Share"), width: "8rem" },
		{ key: "delta", label: __("vs prior"), align: "right" },
	].filter(Boolean),
)

const sortedRows = computed(() => {
	const key = activeSortKey.value
	const direction = descending.value ? -1 : 1
	return props.series
		.map((s) => ({ ...s, key: `${s.name}|${s.provider || ""}` }))
		.sort((a, b) => {
			if (typeof a[key] === "string" || typeof b[key] === "string") {
				return direction * String(a[key] || "").localeCompare(String(b[key] || ""))
			}
			return direction * ((a[key] ?? -Infinity) - (b[key] ?? -Infinity))
		})
})

const totalRow = computed(() => ({
	...props.total,
	key: "__total",
	isTotal: true,
	name: __("Total"),
	provider: "",
	share: 100,
}))

function sortBy(key) {
	if (sortKey.value === key) {
		descending.value = !descending.value
	} else {
		sortKey.value = key
		descending.value = true
	}
}

function format(key, value) {
	if (key === "runs") return fmtInt(value)
	if (key === "cache_hit_rate") return fmtPct(value, 0)
	if (TOKEN_KEYS.includes(key)) return fmtCompact(value)
	if (CURRENCY_KEYS.includes(key)) return fmtCurrency(value)
	return value ?? ""
}

function titleFor(key, value) {
	if (TOKEN_KEYS.includes(key)) return fmtInt(value)
	if (CURRENCY_KEYS.includes(key)) return fmtCurrencyExact(value)
	return ""
}
</script>
