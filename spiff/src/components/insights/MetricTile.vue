<template>
	<div class="bg-white rounded-lg border border-gray-200 p-4">
		<div v-if="loading" class="space-y-3 animate-pulse">
			<div class="h-3 bg-gray-200 rounded w-20"></div>
			<div class="h-7 bg-gray-200 rounded w-16"></div>
		</div>
		<template v-else>
			<div class="flex items-center justify-between gap-2 mb-2">
				<span class="text-xs text-gray-500 uppercase tracking-wide font-medium truncate">{{ label }}</span>
				<span
					v-if="delta !== undefined"
					class="shrink-0 text-[11px] font-medium rounded px-1.5 py-0.5"
					:class="deltaClasses"
				>
					{{ deltaText }}
				</span>
			</div>
			<div class="text-2xl font-bold text-gray-900" :title="valueTitle || undefined">{{ value }}</div>
			<div v-if="subtitle" class="text-xs text-gray-500 mt-1">{{ subtitle }}</div>
			<svg
				v-if="sparkline && sparkline.length > 1"
				viewBox="0 0 100 24"
				preserveAspectRatio="none"
				class="w-full h-6 mt-2 text-gray-400"
			>
				<polyline :points="sparkPoints" fill="none" stroke="currentColor" stroke-width="1.5" />
			</svg>
		</template>
	</div>
</template>

<script setup>
import { computed } from "vue"
import { fmtDelta } from "@/utils/formatters"

const props = defineProps({
	label: { type: String, required: true },
	// Preformatted by the caller with utils/formatters.js; this component does no rounding.
	value: { type: String, default: "" },
	valueTitle: { type: String, default: "" },
	delta: { type: Number, default: undefined },
	deltaKind: { type: String, default: "pct" }, // "pct" | "pt"
	goodDirection: { type: String, default: "up" }, // "up" | "down"
	subtitle: { type: String, default: "" },
	sparkline: { type: Array, default: null },
	loading: { type: Boolean, default: false },
})

const deltaText = computed(() => fmtDelta(props.delta, props.deltaKind))

const deltaTone = computed(() => {
	if (props.delta === null) return "gray"
	const s = props.goodDirection === "down" ? -props.delta : props.delta
	if (s < -2) return "red"
	if (s > 2) return "green"
	return "gray"
})

const deltaClasses = computed(() => {
	return {
		red: "bg-red-50 text-red-700",
		green: "bg-green-50 text-green-700",
		gray: "bg-gray-100 text-gray-600",
	}[deltaTone.value]
})

const sparkPoints = computed(() => {
	const data = props.sparkline
	if (!data || data.length < 2) return ""
	const width = 100
	const height = 24
	const max = Math.max(...data)
	const min = Math.min(...data)
	const range = max - min || 1
	const step = width / (data.length - 1)
	return data
		.map((v, i) => {
			const x = i * step
			const y = height - ((v - min) / range) * height
			return `${x},${y}`
		})
		.join(" ")
})
</script>
