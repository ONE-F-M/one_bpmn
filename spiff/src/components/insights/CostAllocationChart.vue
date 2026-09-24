<template>
	<div class="bg-white rounded-lg shadow-sm p-4">
		<div class="flex items-baseline justify-between">
			<h3 class="text-sm font-medium text-gray-900">Cost by {{ groupLabel }}</h3>
			<span class="text-xs text-gray-500">{{ subtitle }}</span>
		</div>
		<div class="alloc-chart h-64">
			<AxisChart :config="config" />
		</div>
	</div>
</template>

<script setup>
import { computed } from "vue"
import { AxisChart } from "frappe-ui"
import { dayjs } from "@/dayjs"
import { fmtDateRange } from "@/utils/formatters"

const props = defineProps({
	report: { type: Object, required: true },
	series: { type: Array, required: true },
	colors: { type: Object, required: true },
	groupLabel: { type: String, required: true },
})

const subtitle = computed(() =>
	`${fmtDateRange(props.report.from_date, props.report.to_date)}, ${props.report.grain}ly`
)

function bucketLabel(start, next) {
	if (props.report.grain === "month") return dayjs(start).format("MMM YYYY")
	const end = next ? dayjs(next).subtract(1, "day") : dayjs(props.report.to_date)
	return fmtDateRange(start, end.format("YYYY-MM-DD"))
}

const config = computed(() => {
	const buckets = props.report.buckets
	const data = buckets.map((bucket, i) => {
		const row = { bucket: bucketLabel(bucket, buckets[i + 1]) }
		for (const node of props.series) row[node.label] = node.by_bucket[bucket]
		return row
	})
	return {
		data,
		title: "",
		xAxis: { key: "bucket", type: "category" },
		yAxis: { title: "Cost" },
		stacked: true,
		series: props.series.map((node) => ({
			name: node.label,
			type: "bar",
			stackName: "cost",
			color: props.colors[node.key],
			// A 2px surface gap keeps neighbouring segments readable.
			echartOptions: { itemStyle: { borderColor: "#ffffff", borderWidth: 2 } },
		})),
	}
})
</script>

<style scoped></style>
