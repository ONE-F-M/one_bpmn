<template>
	<div class="bg-white rounded-lg shadow-sm p-4">
		<div class="flex items-baseline justify-between">
			<h3 class="text-sm font-medium text-gray-900">{{ title }}</h3>
			<span
				class="text-xs text-gray-500"
				:title="fmtCurrencyExact(total)"
			>{{ fmtCurrency(total) }}</span>
		</div>
		<div class="relative alloc-chart h-36 mt-1">
			<ECharts :options="options" />
			<div
				class="absolute inset-0 flex flex-col items-center justify-center pointer-events-none text-center"
			>
				<div class="text-sm font-semibold text-gray-900">{{ top.pct }}%</div>
				<div class="text-xs text-gray-500 truncate max-w-[84px]">{{ top.label }}</div>
			</div>
		</div>
		<ul class="mt-2 space-y-1">
			<li
				v-for="slice in ranked"
				:key="slice.key"
				class="flex items-center gap-2 text-xs"
			>
				<span
					class="w-2 h-2 rounded-full shrink-0"
					:style="dotStyleOf(slice)"
				></span>
				<span
					class="truncate flex-1 text-gray-700"
					:title="slice.label"
				>{{ slice.label }}</span>
				<span class="text-gray-500 whitespace-nowrap">{{ fmtCurrency(slice.value) }} · {{ slice.pct }}%</span>
			</li>
		</ul>
	</div>
</template>

<script setup>
import { computed } from "vue"
import { ECharts } from "frappe-ui"
import { fmtCurrency, fmtCurrencyExact } from "@/utils/formatters"
import { escapeHtml, rankSlices } from "@/utils/costAllocation"

const props = defineProps({
	slices: { type: Array, required: true },
	colors: { type: Object, required: true },
	title: { type: String, required: true },
	total: { type: Number, required: true },
})

const ranked = computed(() => rankSlices(props.slices))
const top = computed(() => ranked.value[0])

function dotStyleOf(slice) {
	return { background: props.colors[slice.key] }
}

// The ring alone is drawn on the canvas; the centre and legend are HTML so long names never overlap it.
const options = computed(() => ({
	animation: true,
	color: ranked.value.map((s) => props.colors[s.key]),
	tooltip: {
		trigger: "item",
		confine: true,
		formatter: (p) => `<div class="flex items-center justify-between gap-5"><div>${escapeHtml(p.name)}</div>
			<div class="font-bold">${fmtCurrency(p.value)} (${ranked.value[p.dataIndex].pct}%)</div></div>`,
	},
	series: [{
		type: "pie",
		radius: ["62%", "88%"],
		center: ["50%", "50%"],
		itemStyle: { borderColor: "#ffffff", borderWidth: 2 },
		label: { show: false },
		emphasis: { scaleSize: 3 },
		data: ranked.value.map((s) => ({ name: s.label, value: s.value })),
	}],
}))
</script>

<style scoped></style>
