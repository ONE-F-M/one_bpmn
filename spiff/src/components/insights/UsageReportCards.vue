<template>
	<div class="space-y-2">
		<div
			v-for="row in series"
			:key="`${row.name}|${row.provider || ''}`"
			class="bg-white rounded-lg border border-gray-200 p-3"
		>
			<div class="flex items-center justify-between gap-3">
				<span class="text-sm font-medium text-gray-900 truncate">{{ row.name }}</span>
				<span
					class="text-sm font-semibold text-gray-900 whitespace-nowrap"
					:title="fmtCurrencyExact(row.cost)"
				>
					{{ fmtCurrency(row.cost) }}
				</span>
			</div>
			<div class="flex items-center gap-2 mt-2">
				<ShareBar
					class="flex-1"
					:share="row.share || 0"
					:color="colors[row.name]"
				/>
				<span class="text-xs text-gray-600 whitespace-nowrap">{{ fmtPct(row.share, 0) }} {{ __("of spend") }}</span>
				<DeltaPill
					:delta="row.delta"
					good-direction="down"
				/>
				<span class="text-xs text-gray-500 whitespace-nowrap">{{ __("vs prior") }}</span>
			</div>
		</div>
		<div class="bg-gray-50 rounded-lg border border-gray-200 p-3">
			<div class="flex items-center justify-between gap-3">
				<span class="text-sm font-semibold text-gray-900">{{ __("Total") }}</span>
				<span
					class="text-sm font-semibold text-gray-900 whitespace-nowrap"
					:title="fmtCurrencyExact(total.cost)"
				>
					{{ fmtCurrency(total.cost) }}
				</span>
			</div>
			<div class="flex items-center gap-2 text-xs text-gray-500 mt-1">
				<span>{{ fmtInt(total.runs) }} {{ __("runs") }} · {{ fmtCompact(total.tokens) }} {{ __("tokens") }}</span>
				<DeltaPill
					:delta="total.delta"
					good-direction="down"
				/>
				<span>{{ priorLabel }}</span>
			</div>
		</div>
	</div>
</template>

<script setup>
import DeltaPill from "@/components/insights/DeltaPill.vue"
import ShareBar from "@/components/insights/ShareBar.vue"
import { fmtCompact, fmtCurrency, fmtCurrencyExact, fmtInt, fmtPct } from "@/utils/formatters"

defineProps({
	series: { type: Array, required: true },
	total: { type: Object, required: true },
	colors: { type: Object, required: true },
	priorLabel: { type: String, default: "" },
})

const __ = (window.__ && typeof window.__ === "function") ? window.__ : (s) => s
</script>
