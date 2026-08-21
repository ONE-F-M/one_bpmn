<template>
	<div class="w-1/3 flex flex-col border-r bg-white overflow-hidden">
		<div class="px-4 h-10 border-b bg-gray-50/60 shrink-0 flex items-center gap-2">
			<Icon icon="lucide:list-tree" class="w-4 h-4 text-gray-500" />
			<span class="text-sm font-semibold text-gray-700">Instance History</span>
		</div>
		<div class="flex-1 overflow-y-auto custom-scrollbar">
			<div v-if="taskList.length === 0" class="text-sm text-gray-400 italic p-4 text-center">
				<Icon icon="lucide:info" class="w-5 h-5 opacity-40 mx-auto mb-2" />
				No task history available.
			</div>
			<div v-else class="divide-y divide-gray-100">
				<div
					v-for="node in taskList"
					:key="node.id"
					@click="$emit('select', node)"
					class="flex items-center gap-2 py-2 pr-3 cursor-pointer transition-colors text-[13px]"
					:class="isSelected(node) ? 'border-l-2 border-gray-500' : 'hover:bg-gray-50 border-l-2 border-transparent'"
					:style="{
						paddingLeft: (12 + (node.depth || 0) * 20) + 'px',
						...(isSelected(node) ? { backgroundColor: 'rgba(107, 114, 128, 0.12)' } : {}),
					}"
				>
					<!-- Nesting marker for tasks inside a subprocess -->
					<Icon
						v-if="node.depth"
						icon="lucide:corner-down-right"
						class="w-3.5 h-3.5 shrink-0 text-gray-300"
					/>
					<!-- AI tool call (WI-001426): called by the agent's LLM loop,
					     not executed as a flow step — same colours as executed
					     steps; the AI chip marks the provenance. -->
					<template v-if="node.isAiToolCall">
						<Icon
							:icon="node.callStatus === 'Error' ? 'lucide:alert-circle' : 'lucide:check-circle-2'"
							class="w-4 h-4 shrink-0"
							:class="node.callStatus === 'Error' ? 'text-red-500' : 'text-green-500'"
						/>
						<span
							class="truncate"
							:class="isSelected(node) ? 'font-semibold text-gray-900' : 'text-gray-700'"
							:title="aiCallTooltip(node)"
						>{{ node.name }}</span>
						<span
							class="ml-auto shrink-0 text-[10px] font-semibold px-1.5 py-0.5 rounded"
							:class="node.callStatus === 'Error' ? 'bg-red-50 text-red-600 border border-red-200' : 'bg-blue-50 text-blue-600 border border-blue-200'"
							:title="aiCallTooltip(node)"
						>AI</span>
					</template>
					<template v-else>
						<!-- State icon -->
						<Icon v-if="node.stateLabel === 'Completed'" icon="lucide:check-circle-2" class="w-4 h-4 text-green-500 shrink-0" />
						<Icon v-else-if="node.stateLabel === 'Error'" icon="lucide:alert-circle" class="w-4 h-4 text-red-500 shrink-0" />
						<Icon v-else-if="node.stateLabel === 'Cancelled'" icon="lucide:x-circle" class="w-4 h-4 text-gray-400 shrink-0" />
						<Icon v-else icon="lucide:circle" class="w-4 h-4 text-gray-300 shrink-0" />
						<!-- Task name -->
						<span
							class="truncate"
							:class="isSelected(node) ? 'font-semibold text-gray-900' : 'text-gray-700'"
						>{{ node.name }}</span>
					</template>
				</div>
			</div>
		</div>
	</div>
</template>

<script setup>
import { Icon } from "@iconify/vue"

const props = defineProps({
	taskList: { type: Array, default: () => [] },
	selectedNodeId: { type: String, default: null },
	selectedBpmnId: { type: String, default: null },
})

defineEmits(["select"])

function isSelected(node) {
	if (node.isAiToolCall) return false // selection belongs to the agent task row
	if (props.selectedNodeId) return props.selectedNodeId === node.id
	if (props.selectedBpmnId) return props.selectedBpmnId === node.bpmnId
	return false
}

function aiCallTooltip(node) {
	const lines = ["Called by the AI agent — not a flow step"]
	if (node.argsPreview) lines.push(`args: ${node.argsPreview}`)
	if (node.resultPreview) lines.push(`result: ${node.resultPreview}`)
	lines.push("Click to open the agent's AI Run tab")
	return lines.join("\n")
}
</script>

<style scoped>
.custom-scrollbar::-webkit-scrollbar { width: 6px; height: 6px; }
.custom-scrollbar::-webkit-scrollbar-track { background: rgba(0,0,0,0.02); }
.custom-scrollbar::-webkit-scrollbar-thumb { background: rgba(0,0,0,0.1); border-radius: 10px; }
.custom-scrollbar::-webkit-scrollbar-thumb:hover { background: rgba(0,0,0,0.2); }
</style>
