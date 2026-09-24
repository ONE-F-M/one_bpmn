<template>
	<!--
		A run as the tree it really was. One row per step, opened to read what
		it said and did; under a step that started other runs, those runs nest
		with their own steps, so a turn reads as orchestrator call, tool, inner
		call, tool, each with its cost and time. The component renders itself
		for the nested runs. A nested run arrives with its totals only and
		fetches its steps the first time it is opened.
	-->
	<div :class="depth > 0 ? 'border-l-2 border-indigo-100 pl-3 mt-2' : ''">
		<div
			v-if="depth > 0"
			class="flex flex-wrap items-center gap-2 py-1 text-xs cursor-pointer hover:bg-gray-50 rounded"
			@click="toggleRun"
		>
			<Icon :icon="expanded ? 'lucide:chevron-down' : 'lucide:chevron-right'" class="w-3 h-3 text-gray-400" />
			<span class="font-mono text-gray-700">{{ view.run.name }}</span>
			<span class="text-gray-500">{{ view.run.bpmn_label || view.run.bpmn_id }}</span>
			<span class="text-gray-400">{{ view.run.agent_configuration || view.run.model }}</span>
			<Badge :theme="view.run.status === 'Success' ? 'green' : 'red'" size="sm">{{ view.run.status }}</Badge>
			<span class="text-gray-500">{{ fmtDuration(view.run.duration_ms) }}</span>
			<span
				class="text-gray-500"
				:title="fmtNum(viewTokens)"
			>
				{{ fmtCompact(viewTokens) }} tokens
			</span>
			<span
				class="text-gray-500"
				:title="fmtCurrencyExact(viewCost)"
			>
				{{ fmtCurrency(viewCost) }}
			</span>
			<RouterLink :to="`/processa/runs/${view.run.name}`" class="text-blue-600 hover:underline ml-auto" @click.stop>open</RouterLink>
		</div>

		<div v-if="expanded && loading" class="text-xs text-gray-500 py-1">Loading steps…</div>
		<ErrorMessage v-else-if="expanded && loadError" :message="loadError" />

		<!--
			Every level uses the same fixed column widths; Tool absorbs the
			remainder, since a step number needs a number's worth of space and
			the tool name is the part worth reading.
		-->
		<table v-else-if="expanded" class="w-full table-fixed">
			<colgroup>
				<col class="w-12" />
				<col class="w-24" />
				<col />
				<col class="w-36" />
				<col class="w-24" />
				<col class="w-24" />
				<col class="w-24" />
			</colgroup>
			<thead v-if="depth === 0">
				<tr class="border-b border-gray-200">
					<th class="text-left text-xs text-gray-400 font-medium py-1 px-2">Step</th>
					<th class="text-left text-xs text-gray-400 font-medium py-1 px-2">Role</th>
					<th class="text-left text-xs text-gray-400 font-medium py-1 px-2">
						<span class="flex items-center">
							Tool
							<span class="ml-auto flex gap-2 font-normal normal-case">
								<button class="hover:text-gray-900" @click="setAll(true)">Expand all</button>
								<button class="hover:text-gray-900" @click="setAll(false)">Collapse all</button>
							</span>
						</span>
					</th>
					<th class="text-left text-xs text-gray-400 font-medium py-1 px-2">Error</th>
					<th class="text-right text-xs text-gray-400 font-medium py-1 px-2">Latency</th>
					<th class="text-right text-xs text-gray-400 font-medium py-1 px-2">Tokens</th>
					<th class="text-right text-xs text-gray-400 font-medium py-1 px-2">Cost</th>
				</tr>
			</thead>
			<tbody>
				<template v-for="(step, si) in view.steps" :key="step.name">
					<tr
						class="border-b border-gray-50 cursor-pointer hover:bg-gray-200"
						:class="step.error_code ? 'bg-red-50' : si % 2 ? 'bg-gray-100' : 'bg-white'"
						@click="toggleStep(step.name)"
					>
						<td class="py-1.5 px-2 text-xs text-gray-500">
							<span class="inline-flex items-center gap-1">
								<Icon :icon="openSteps.has(step.name) ? 'lucide:chevron-down' : 'lucide:chevron-right'" class="w-3 h-3 text-gray-400" />
								{{ step.step_index }}
							</span>
						</td>
						<td class="py-1.5 px-2 text-xs text-gray-600">
							{{ step.role }}
							<span v-if="step.sub_call" class="ml-1 text-indigo-600">sub-call</span>
						</td>
						<td class="py-1.5 px-2 text-xs text-gray-600 font-mono break-words">
							<template v-if="step.sub_call">
								{{ step.sub_call.tool }}
								<span class="text-gray-400 font-sans">via {{ step.sub_call.model }}</span>
							</template>
							<template v-else-if="step.tool_names.length">{{ step.tool_names.join(", ") }}</template>
							<span v-else-if="step.content" class="text-gray-400 font-sans">{{ step.content.slice(0, 80) }}</span>
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
						<td class="py-1.5 px-2 text-xs text-gray-600 text-right">{{ fmtDuration(step.latency_ms) }}</td>
						<td
							class="py-1.5 px-2 text-xs text-gray-600 text-right"
							:title="fmtNum(stepTokens(step))"
						>
							{{ fmtCompact(stepTokens(step)) }}
						</td>
						<td
							class="py-1.5 px-2 text-xs text-gray-600 text-right"
							:title="fmtCurrencyExact(step.cost)"
						>
							{{ fmtCurrency(step.cost) }}
						</td>
					</tr>
					<tr v-if="openSteps.has(step.name)" class="border-b border-gray-50 bg-gray-50/60">
						<td></td>
						<td colspan="6" class="px-2 py-2">
							<StepBody :step="step" :show-system="true" />
						</td>
					</tr>
					<tr v-if="step.child_runs && step.child_runs.length">
						<td colspan="7" class="px-2 pb-1">
							<RunTree v-for="child in step.child_runs" :key="child.run.name" :node="child" :depth="depth + 1" />
						</td>
					</tr>
				</template>
				<tr v-if="view.unplaced_children && view.unplaced_children.length">
					<td colspan="7" class="px-2 pb-1">
						<div class="text-xs text-gray-400 pt-2">Runs started during this run</div>
						<RunTree v-for="child in view.unplaced_children" :key="child.run.name" :node="child" :depth="depth + 1" />
					</td>
				</tr>
			</tbody>
		</table>

		<div v-if="depth === 0 && view.rollup && view.rollup.runs > 1" class="flex flex-wrap gap-4 pt-2 text-xs text-gray-600">
			<span>Whole turn: {{ view.rollup.runs }} runs</span>
			<span :title="fmtNum(view.rollup.total_tokens)">{{ fmtCompact(view.rollup.total_tokens) }} tokens</span>
			<span :title="fmtCurrencyExact(view.rollup.estimated_cost)">{{ fmtCurrency(view.rollup.estimated_cost) }}</span>
			<span
				class="text-gray-400"
				:title="`${fmtNum(view.run.total_tokens)} tokens, ${fmtCurrencyExact(view.run.estimated_cost)}`"
			>
				(this run alone: {{ fmtCompact(view.run.total_tokens) }} tokens, {{ fmtCurrency(view.run.estimated_cost) }})
			</span>
		</div>
	</div>
</template>

<script setup>
import { Badge, ErrorMessage, frappeRequest } from "frappe-ui"
import { Icon } from "@iconify/vue"
import { computed, ref, watch } from "vue"
import { RouterLink } from "vue-router"
import StepBody from "@/components/insights/StepBody.vue"
import { fmtInt as fmtNum, fmtCompact, fmtCurrency, fmtCurrencyExact, fmtDuration } from "@/utils/formatters"

const props = defineProps({
	node: { type: Object, required: true },
	depth: { type: Number, default: 0 },
})

// A nested run's steps replace the stub the tree arrived with, once fetched.
const fetched = ref(null)
const view = computed(() => fetched.value || props.node)
const viewTokens = computed(() => view.value.rollup?.total_tokens ?? view.value.run.total_tokens)
const viewCost = computed(() => view.value.rollup?.estimated_cost ?? view.value.run.estimated_cost)
const expanded = ref(props.depth === 0)
const loading = ref(false)
const loadError = ref("")

// A failed step is the one the reader came for, so it starts open.
const openSteps = ref(new Set())
watch(
	() => view.value.steps,
	(rows) => {
		openSteps.value = new Set((rows || []).filter((s) => s.error_code).map((s) => s.name))
	},
	{ immediate: true },
)

async function toggleRun() {
	expanded.value = !expanded.value
	if (!expanded.value || props.node.steps_loaded !== false || fetched.value || loading.value) return
	loading.value = true
	loadError.value = ""
	try {
		fetched.value = await frappeRequest({
			url: "/api/method/one_bpmn.api.insights_api.get_turn_steps",
			params: { run_name: props.node.run.name },
		})
	} catch (e) {
		loadError.value = e.message || String(e)
	} finally {
		loading.value = false
	}
}

function toggleStep(name) {
	const next = new Set(openSteps.value)
	next.has(name) ? next.delete(name) : next.add(name)
	openSteps.value = next
}

function setAll(on) {
	openSteps.value = on ? new Set((view.value.steps || []).map((s) => s.name)) : new Set()
}

function stepTokens(step) {
	return (step.prompt_tokens ?? 0) + (step.completion_tokens ?? 0)
}
</script>
