<template>
	<div class="bg-white rounded-lg shadow-sm p-4">
		<div class="flex items-baseline justify-between">
			<h3 class="text-sm font-medium text-gray-900">{{ title }}</h3>
			<span
				class="text-xs text-gray-500"
				:title="fmtCurrencyExact(total)"
			>{{ fmtCurrency(total) }}</span>
		</div>
		<div class="alloc-chart h-64">
			<DonutChart :config="config" />
		</div>
	</div>
</template>

<script setup>
import { computed } from "vue"
import { DonutChart } from "frappe-ui"
import { fmtCurrency, fmtCurrencyExact } from "@/utils/formatters"

const props = defineProps({
	slices: { type: Array, required: true },
	colors: { type: Object, required: true },
	title: { type: String, required: true },
	total: { type: Number, required: true },
})

// DonutChart sorts slices by value and colours them in that order, so colours follow the same sort.
const config = computed(() => {
	const data = [...props.slices].sort((a, b) => b.value - a.value)
	return {
		data,
		title: "",
		categoryColumn: "label",
		valueColumn: "value",
		colors: data.map((s) => props.colors[s.key]),
	}
})
</script>

<style scoped></style>
