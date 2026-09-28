<template>
	<div class="bg-white rounded-lg border border-gray-200 p-4">
		<div class="flex items-baseline justify-between gap-3">
			<h3 class="text-sm font-semibold text-gray-900">{{ title }}</h3>
			<span
				class="text-xs text-gray-500"
				:title="fmtCurrencyExact(total)"
			>{{ fmtCurrency(total) }}</span>
		</div>
		<div class="flex items-center gap-2 h-[180px] sm:h-[260px]">
			<div class="relative alloc-chart alloc-donut w-[112px] shrink-0 h-full">
				<ECharts :options="options" />
				<div
					class="absolute inset-0 flex flex-col items-center justify-center pointer-events-none text-center"
				>
					<div class="text-sm font-semibold text-gray-900">{{ top.pct }}%</div>
					<div class="text-[11px] text-gray-500 truncate max-w-[84px]">{{ top.label }}</div>
				</div>
			</div>
			<ul class="flex-1 space-y-2 min-w-0">
				<li
					v-for="slice in ranked"
					:key="slice.key"
					class="flex items-center gap-1.5 text-[11px]"
				>
					<span
						class="w-2 h-2 rounded-full shrink-0"
						:style="dotStyleOf(slice)"
					></span>
					<span
						class="truncate text-gray-600"
						:title="slice.label"
					>{{ slice.label }}</span>
					<span class="ml-auto shrink-0 text-gray-500">{{ fmtCurrency(slice.value) }} · {{ slice.pct }}%</span>
				</li>
			</ul>
		</div>
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
	animation: false,
	color: ranked.value.map((s) => props.colors[s.key]),
	tooltip: {
		trigger: "item",
		confine: true,
		formatter: (p) => `<div class="flex items-center justify-between gap-5"><div>${escapeHtml(p.name)}</div>
			<div class="font-bold">${fmtCurrency(p.value)} (${ranked.value[p.dataIndex].pct}%)</div></div>`,
	},
	series: [{
		type: "pie",
		radius: ["58%", "82%"],
		center: ["50%", "50%"],
		itemStyle: { borderColor: "#ffffff", borderWidth: 2 },
		label: { show: false },
		emphasis: { scaleSize: 3 },
		data: ranked.value.map((s) => ({ name: s.label, value: s.value })),
	}],
}))
</script>

<style scoped>
/* The shared chart root pads itself by 16px; the ring needs the whole column. */
.alloc-donut :deep(> div) {
	padding: 0;
}
</style>
