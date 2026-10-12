<template>
	<div class="rounded border border-gray-200 bg-gray-50 px-2 py-1.5 text-xs">
		<div class="mb-1 font-medium text-gray-600">{{ __("Tool calls the agent should make") }}</div>
		<div
			v-for="(call, i) in calls"
			:key="i"
			class="call-row flex items-start gap-2 border-t border-gray-200 py-1"
		>
			<span class="w-5 shrink-0 text-gray-400">{{ i + 1 }}.</span>
			<div class="min-w-0 flex-1 font-mono">
				<div class="break-all text-gray-800">{{ call.tool }}({{ argsText(call) }})</div>
				<div
					v-if="call.result"
					class="break-all text-gray-500"
				>
					=> {{ call.result }}
				</div>
			</div>
			<button
				type="button"
				class="shrink-0 text-gray-400 hover:text-red-600"
				:title="__('Remove this call')"
				@click="remove(i)"
			>
				{{ __("Remove") }}
			</button>
		</div>
	</div>
</template>

<script setup>
import { computed } from "vue"

const props = defineProps({
	modelValue: { type: [String, Array], default: null },
})
const emit = defineEmits(["update:modelValue"])

const __ = (window.__ && typeof window.__ === "function") ? window.__ : (s) => s

const calls = computed(() => {
	if (Array.isArray(props.modelValue)) return props.modelValue
	return props.modelValue ? JSON.parse(props.modelValue) : []
})

function argsText(call) {
	return JSON.stringify(call.args || {})
}

function remove(index) {
	const kept = calls.value.filter((_, i) => i !== index)
	emit("update:modelValue", kept.length ? JSON.stringify(kept) : null)
}
</script>

<style scoped>
.call-row:first-of-type {
	border-top-width: 0;
}
</style>
