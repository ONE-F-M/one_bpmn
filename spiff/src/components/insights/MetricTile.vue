<template>
	<div class="bg-white p-4">
		<div
			v-if="loading"
			class="space-y-3 animate-pulse"
		>
			<div class="h-3 bg-gray-200 rounded w-20"></div>
			<div class="h-7 bg-gray-200 rounded w-16"></div>
		</div>
		<template v-else>
			<div class="flex items-start justify-between gap-2 mb-2">
				<span class="text-xs text-gray-500 uppercase tracking-wide font-medium">{{ label }}</span>
				<svg
					v-if="hasSparkline"
					viewBox="0 0 60 18"
					preserveAspectRatio="none"
					class="shrink-0 w-[44px] sm:w-[60px] h-[18px]"
					:class="sparklineClass"
				>
					<polyline
						:points="sparkPoints"
						fill="none"
						stroke="currentColor"
						stroke-width="1.5"
					/>
				</svg>
			</div>
			<div
				class="text-2xl font-bold whitespace-nowrap"
				:class="valueClass"
				:title="valueTitle || undefined"
			>
				{{ value }}
			</div>
			<div
				v-if="delta !== undefined || subtitle"
				class="flex items-center gap-1.5 mt-1 text-xs text-gray-500 whitespace-nowrap"
			>
				<DeltaPill
					v-if="delta !== undefined"
					:delta="delta"
					:kind="deltaKind"
					:good-direction="goodDirection"
				/>
				<span
					v-if="subtitle"
					:class="{ 'hidden sm:inline': subtitleShort }"
				>
					{{ subtitle }}
				</span>
				<span
					v-if="subtitleShort"
					class="sm:hidden"
				>
					{{ subtitleShort }}
				</span>
			</div>
		</template>
	</div>
</template>

<script setup>
import { computed } from "vue"
import DeltaPill from "@/components/insights/DeltaPill.vue"

const props = defineProps({
	label: { type: String, required: true },
	// Preformatted by the caller with utils/formatters.js; this component does no rounding.
	value: { type: String, default: "" },
	valueTitle: { type: String, default: "" },
	valueClass: { type: String, default: "text-gray-900" },
	delta: { type: Number, default: undefined },
	deltaKind: { type: String, default: "pct" }, // "pct" | "pt"
	goodDirection: { type: String, default: "up" }, // "up" | "down"
	subtitle: { type: String, default: "" },
	subtitleShort: { type: String, default: "" },
	sparkline: { type: Array, default: null },
	sparklineClass: { type: String, default: "text-gray-500" },
	loading: { type: Boolean, default: false },
})

const hasSparkline = computed(() => Array.isArray(props.sparkline) && props.sparkline.length > 0)

const sparkPoints = computed(() => {
	const data = props.sparkline.length === 1 ? [props.sparkline[0], props.sparkline[0]] : props.sparkline
	const width = 60
	const height = 18
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
