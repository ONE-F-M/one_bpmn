<template>
	<span
		class="shrink-0 text-[11px] font-medium rounded px-1.5 py-0.5 whitespace-nowrap"
		:class="toneClasses"
	>
		{{ fmtDelta(delta, kind) }}
	</span>
</template>

<script setup>
import { computed } from "vue"
import { fmtDelta } from "@/utils/formatters"

const props = defineProps({
	delta: { type: Number, default: null },
	kind: { type: String, default: "pct" }, // "pct" | "pt"
	goodDirection: { type: String, default: "up" }, // "up" | "down"
})

const toneClasses = computed(() => {
	const signed = props.delta === null ? 0 : props.goodDirection === "down" ? -props.delta : props.delta
	if (signed < -2) return "bg-red-50 text-red-700"
	if (signed > 2) return "bg-green-50 text-green-700"
	return "text-gray-500"
})
</script>
