<template>
	<div v-if="turns.length || state">
		<div class="text-xs uppercase tracking-wide text-gray-500 font-medium mb-2">
			{{ __("Earlier conversation") }}
			<span class="normal-case tracking-normal text-gray-400">· {{ __("loaded before the prompt, as the case holds it now") }}</span>
		</div>
		<div class="space-y-1.5">
			<div
				v-for="(turn, i) in turns"
				:key="i"
				class="flex gap-2 text-xs"
			>
				<span class="shrink-0 w-16 font-medium text-gray-500">{{ turn.role === "User" ? __("User") : __("Agent") }}</span>
				<pre
					class="flex-1 rounded px-2 py-1 whitespace-pre-wrap font-sans"
					:class="turn.role === 'User' ? 'bg-gray-50 text-gray-800' : 'bg-blue-50 text-gray-800'"
				>{{ turn.text }}</pre>
			</div>
		</div>
		<details
			v-if="state"
			class="mt-2"
		>
			<summary class="text-xs text-gray-500 cursor-pointer">{{ __("Saved state the agent started with") }}</summary>
			<pre class="text-xs bg-gray-50 rounded p-3 mt-2 whitespace-pre-wrap overflow-auto max-h-64">{{ JSON.stringify(state, null, 2) }}</pre>
		</details>
	</div>
</template>

<script setup>
import { computed } from "vue"
import { earlierTurns, savedState } from "@/utils/evalContext"

const props = defineProps({
	context: { type: Object, default: null },
})

const __ = (window.__ && typeof window.__ === "function") ? window.__ : (s) => s
const turns = computed(() => earlierTurns(props.context))
const state = computed(() => savedState(props.context))
</script>
