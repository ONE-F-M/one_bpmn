<template>
	<div class="flex h-full items-center gap-3">
		<div class="w-1/2 h-full">
			<ECharts :options="options" />
		</div>
		<ul class="w-1/2 space-y-2 min-w-0">
			<li
				v-for="slice in slices"
				:key="slice.name"
				class="flex items-center gap-2 text-xs text-gray-600"
			>
				<svg
					viewBox="0 0 8 8"
					class="shrink-0 w-2 h-2"
				>
					<rect
						width="8"
						height="8"
						rx="1"
						:fill="colors[slice.name]"
					/>
				</svg>
				<span
					class="truncate"
					:title="slice.name"
				>{{ slice.name }}</span>
				<span class="ml-auto shrink-0 text-gray-500">{{ percent(slice.cost) }}%</span>
			</li>
		</ul>
	</div>
</template>

<script setup>
import { computed } from "vue"
import { ECharts } from "frappe-ui"
import { fmtCurrency } from "@/utils/formatters"

const props = defineProps({
	slices: { type: Array, required: true },
	colors: { type: Object, required: true },
})

const total = computed(() => props.slices.reduce((sum, s) => sum + s.cost, 0))

function percent(cost) {
	return total.value ? Math.round((cost / total.value) * 100) : 0
}

const options = computed(() => {
	const top = props.slices[0]
	return {
		color: props.slices.map((s) => props.colors[s.name]),
		title: {
			text: top ? `${percent(top.cost)}%` : "",
			subtext: top?.name || "",
			left: "50%",
			top: "center",
			textAlign: "center",
			textStyle: { fontSize: 13, fontWeight: 600, color: "#374151" },
			subtextStyle: { fontSize: 10, color: "#6b7280", width: 70, overflow: "truncate" },
			itemGap: 2,
		},
		tooltip: {
			trigger: "item",
			confine: true,
			formatter: (p) => `${p.name}: ${fmtCurrency(p.value)} (${percent(p.value)}%)`,
		},
		series: [
			{
				type: "pie",
				radius: ["50%", "72%"],
				center: ["50%", "50%"],
				label: { show: false },
				labelLine: { show: false },
				data: props.slices.map((s) => ({ name: s.name, value: s.cost })),
			},
		],
	}
})
</script>
