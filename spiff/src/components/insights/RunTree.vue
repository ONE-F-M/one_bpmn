<template>
	<!--
		WI-002190: a run as the tree it really was. One row per step; under a
		step that started other runs, those runs nest with their own steps, so
		a turn reads as orchestrator call, tool, inner call, tool, each with
		its cost and time. The component renders itself for the nested runs.
	-->
	<div :class="depth > 0 ? 'border-l-2 border-indigo-100 pl-3 mt-2' : ''">
		<div v-if="depth > 0" class="flex flex-wrap items-center gap-2 py-1 text-xs">
			<Icon icon="lucide:corner-down-right" class="w-3 h-3 text-gray-400" />
			<span class="font-mono text-gray-700">{{ node.run.name }}</span>
			<span class="text-gray-500">{{ node.run.bpmn_label || node.run.bpmn_id }}</span>
			<span class="text-gray-400">{{ node.run.agent_configuration || node.run.model }}</span>
			<Badge :theme="node.run.status === 'Success' ? 'green' : 'red'" size="sm">{{ node.run.status }}</Badge>
			<span class="text-gray-500">{{ fmtNum(node.run.duration_ms) }}ms</span>
			<span class="text-gray-500">{{ fmtNum(node.run.total_tokens) }} tokens</span>
			<span class="text-gray-500">${{ (node.run.estimated_cost ?? 0).toFixed(4) }}</span>
		</div>

		<table class="w-full">
			<thead v-if="depth === 0">
				<tr class="border-b border-gray-200">
					<th class="text-left text-xs text-gray-400 font-medium py-1 px-2">Step</th>
					<th class="text-left text-xs text-gray-400 font-medium py-1 px-2">Role</th>
					<th class="text-left text-xs text-gray-400 font-medium py-1 px-2">Tool</th>
					<th class="text-left text-xs text-gray-400 font-medium py-1 px-2">Error</th>
					<th class="text-right text-xs text-gray-400 font-medium py-1 px-2">Latency</th>
					<th class="text-right text-xs text-gray-400 font-medium py-1 px-2">Tokens</th>
					<th class="text-right text-xs text-gray-400 font-medium py-1 px-2">Cost</th>
				</tr>
			</thead>
			<tbody>
				<template v-for="step in node.steps" :key="step.name">
					<tr class="border-b border-gray-50" :class="step.error_code ? 'bg-red-50' : ''">
						<td class="py-1.5 px-2 text-xs text-gray-500">{{ step.step_index }}</td>
						<td class="py-1.5 px-2 text-xs text-gray-600">
							{{ step.role }}
							<span v-if="step.sub_call" class="ml-1 text-indigo-600">sub-call</span>
						</td>
						<td class="py-1.5 px-2 text-xs text-gray-600 font-mono">
							<template v-if="step.sub_call">
								{{ step.sub_call.tool }}
								<span class="text-gray-400 font-sans">via {{ step.sub_call.model }}</span>
							</template>
							<template v-else-if="step.tool_names.length">{{ step.tool_names.join(", ") }}</template>
							<template v-else>—</template>
						</td>
						<td class="py-1.5 px-2 text-xs">
							<span
								v-if="step.error_code"
								class="text-red-700 font-mono cursor-help"
								:title="step.error_message || ''"
							>{{ step.error_code }}</span>
							<span v-else class="text-gray-400">—</span>
						</td>
						<td class="py-1.5 px-2 text-xs text-gray-600 text-right">{{ fmtNum(step.latency_ms) }}ms</td>
						<td class="py-1.5 px-2 text-xs text-gray-600 text-right">{{ fmtNum((step.prompt_tokens ?? 0) + (step.completion_tokens ?? 0)) }}</td>
						<td class="py-1.5 px-2 text-xs text-gray-600 text-right">${{ (step.cost ?? 0).toFixed(4) }}</td>
					</tr>
					<tr v-if="step.child_runs && step.child_runs.length">
						<td colspan="7" class="px-2 pb-1">
							<RunTree v-for="child in step.child_runs" :key="child.run.name" :node="child" :depth="depth + 1" />
						</td>
					</tr>
				</template>
				<tr v-if="node.unplaced_children && node.unplaced_children.length">
					<td colspan="7" class="px-2 pb-1">
						<div class="text-xs text-gray-400 pt-2">Runs started during this run</div>
						<RunTree v-for="child in node.unplaced_children" :key="child.run.name" :node="child" :depth="depth + 1" />
					</td>
				</tr>
			</tbody>
		</table>

		<div v-if="depth === 0 && node.rollup && node.rollup.runs > 1" class="flex flex-wrap gap-4 pt-2 text-xs text-gray-600">
			<span>Whole turn: {{ node.rollup.runs }} runs</span>
			<span>{{ fmtNum(node.rollup.total_tokens) }} tokens</span>
			<span>${{ (node.rollup.estimated_cost ?? 0).toFixed(4) }}</span>
			<span class="text-gray-400">
				(this run alone: {{ fmtNum(node.run.total_tokens) }} tokens, ${{ (node.run.estimated_cost ?? 0).toFixed(4) }})
			</span>
		</div>
	</div>
</template>

<script setup>
import { Badge } from "frappe-ui"
import { Icon } from "@iconify/vue"

defineProps({
	node: { type: Object, required: true },
	depth: { type: Number, default: 0 },
})

const numFormatter = new Intl.NumberFormat("en-US")
function fmtNum(val) { return numFormatter.format(val ?? 0) }
</script>
