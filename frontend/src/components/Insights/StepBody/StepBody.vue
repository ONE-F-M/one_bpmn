<template>
	<!-- What one step said and did: its error, its text, and each tool call
	     with arguments, result and artifact. Shared by the conversation's turn
	     table and the tree, so a step reads the same wherever it is opened. -->
	<div class="space-y-2">
		<div v-if="step.error_message">
			<div class="text-[11px] uppercase text-red-500 mb-0.5">Error</div>
			<pre class="text-xs text-red-800 whitespace-pre-wrap bg-red-50 rounded p-2 max-h-48 overflow-auto">{{ step.error_message }}</pre>
		</div>
		<div v-if="step.content && (step.role !== 'system' || showSystem)">
			<div class="text-[11px] uppercase text-gray-400 mb-0.5">{{ contentLabel }}</div>
			<pre class="text-xs text-gray-700 whitespace-pre-wrap bg-white border rounded p-2 max-h-72 overflow-auto">{{ step.content }}</pre>
		</div>
		<div v-else-if="step.role === 'system'" class="text-xs text-gray-400">System prompt shown above.</div>
		<div v-for="(c, ci) in step.tool_calls || []" :key="ci" class="border rounded bg-white p-2">
			<div class="flex items-center gap-2 text-xs">
				<span class="font-mono font-semibold text-gray-800">{{ c.tool_name }}</span>
				<span class="text-gray-400">{{ c.tool_source }}</span>
				<Badge :theme="c.status === 'Success' ? 'green' : c.status === 'Denied' ? 'orange' : 'red'" size="sm">{{ c.status }}</Badge>
				<span v-if="c.outcome" class="text-gray-500 truncate">{{ c.outcome }}</span>
				<a v-if="c.artifact_file" :href="`/app/file/${c.artifact_file}`" target="_blank" class="ml-auto text-blue-600 hover:underline">artifact file</a>
			</div>
			<div v-if="hasValue(c.tool_args)" class="mt-1">
				<div class="text-[11px] uppercase text-gray-400">Arguments</div>
				<pre class="text-xs text-gray-700 whitespace-pre-wrap max-h-48 overflow-auto">{{ prettyJson(c.tool_args) }}</pre>
			</div>
			<div v-if="c.tool_result" class="mt-1">
				<div class="text-[11px] uppercase text-gray-400">Result</div>
				<pre class="text-xs text-gray-700 whitespace-pre-wrap max-h-48 overflow-auto">{{ prettyJson(c.tool_result) }}</pre>
			</div>
			<div v-if="c.tool_artifact" class="mt-1">
				<div class="text-[11px] uppercase text-gray-400">Artifact</div>
				<pre class="text-xs text-gray-700 whitespace-pre-wrap max-h-48 overflow-auto">{{ c.tool_artifact }}</pre>
			</div>
		</div>
		<div v-if="!step.content && !(step.tool_calls || []).length && !step.error_message && step.role !== 'system'" class="text-xs text-gray-400">
			Nothing recorded for this step.
		</div>
	</div>
</template>

<script setup>
import { Badge } from "frappe-ui"
import { computed } from "vue"
import { prettyJson } from "@/utils/runFormat"

const props = defineProps({
	step: { type: Object, required: true },
	// The turn table shows the system prompt above its steps; the tree has
	// nowhere else to put it.
	showSystem: { type: Boolean, default: false },
})

const contentLabel = computed(() => {
	if (props.step.role === "system") return "System prompt"
	if (props.step.role === "user") return "Input"
	if (props.step.role === "assistant") return "Output"
	return "Narration"
})

function hasValue(v) {
	if (v == null || v === "") return false
	if (typeof v === "object") return Object.keys(v).length > 0
	return v !== "{}"
}
</script>
