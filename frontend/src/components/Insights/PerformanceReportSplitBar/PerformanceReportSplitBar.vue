<template>
	<div class="space-y-1.5">
		<div class="flex h-2 w-full overflow-hidden rounded-full bg-gray-100">
			<div
				v-for="part in parts"
				:key="part.key"
				:class="part.bar"
				:style="{ width: `${part.share}%` }"
			></div>
		</div>
		<div class="flex flex-wrap gap-x-4 gap-y-1 text-xs text-gray-600">
			<span
				v-for="part in parts"
				:key="part.key"
				class="flex items-center gap-1.5 whitespace-nowrap"
			>
				<span
					class="inline-block w-2 h-2 rounded-full"
					:class="part.bar"
				></span>
				{{ part.label }} <span class="font-semibold text-gray-900">{{ fmtPct(part.share, 0) }}</span>
				<span v-if="showAverages">· {{ __("avg") }} {{ fmtDuration(part.avg) }}</span>
			</span>
		</div>
	</div>
</template>

<script setup>
import { computed } from "vue"
import { fmtDuration, fmtPct } from "@/utils/formatters"

const props = defineProps({
	split: { type: Object, required: true },
	showAverages: { type: Boolean, default: true },
})

const __ = (window.__ && typeof window.__ === "function") ? window.__ : (s) => s

const parts = computed(() => [
	{ key: "model", label: __("Model"), bar: "bg-blue-500", share: props.split.model_share, avg: props.split.model_avg_ms },
	{ key: "tool", label: __("Tools"), bar: "bg-amber-500", share: props.split.tool_share, avg: props.split.tool_avg_ms },
	{
		key: "sub_call",
		label: __("Sub-calls"),
		bar: "bg-violet-500",
		share: props.split.sub_call_share,
		avg: props.split.sub_call_avg_ms,
	},
])
</script>

<style scoped>
</style>
