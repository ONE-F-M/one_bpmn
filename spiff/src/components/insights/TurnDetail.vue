<template>
	<div class="space-y-3">
		<div v-if="slowest.length" class="bg-white border rounded-lg px-4 py-3">
			<div class="text-xs font-semibold text-gray-600 mb-2">Slowest steps in this run</div>
			<div v-for="s in slowest" :key="s.name" class="grid items-center gap-3 text-xs py-0.5" style="grid-template-columns: 2rem 16rem 1fr 3rem 4rem">
				<span class="text-gray-400">#{{ s.step_index }}</span>
				<span class="font-mono text-gray-700 truncate">{{ kindLabel(s) }}</span>
				<div class="h-2 bg-gray-100 rounded"><div class="h-2 rounded" :class="barTone(s)" :style="{ width: pct(s.latency_ms, latencyTotal) + '%' }"></div></div>
				<span class="text-right text-gray-400">{{ pct(s.latency_ms, latencyTotal).toFixed(0) }}%</span>
				<span class="text-right font-semibold text-gray-700">{{ fmtMs(s.latency_ms) }}</span>
			</div>
		</div>

		<details v-if="systemPrompt" class="bg-white border rounded-lg px-4 py-2">
			<summary class="text-xs text-gray-600 cursor-pointer">
				System prompt <span class="text-gray-400">{{ systemPrompt.split("\n")[0].slice(0, 120) }}</span>
				<span v-if="run.prompt_hash" class="font-mono text-gray-400 ml-2">{{ run.prompt_hash.slice(0, 12) }}</span>
			</summary>
			<pre class="mt-2 text-xs text-gray-700 whitespace-pre-wrap max-h-96 overflow-auto">{{ systemPrompt }}</pre>
		</details>

		<div class="bg-white border rounded-lg overflow-hidden">
			<div class="flex items-center justify-between px-4 py-2 border-b text-xs text-gray-500">
				<span>{{ timelineLabel }}</span>
				<span class="flex gap-2">
					<button class="hover:text-gray-900" @click="setAll(true)">Expand all</button>
					<button class="hover:text-gray-900" @click="setAll(false)">Collapse all</button>
				</span>
			</div>
			<table class="w-full text-xs table-fixed">
				<colgroup>
					<col class="w-10" /><col class="w-64" /><col /><col class="w-20" /><col class="w-20" /><col class="w-20" />
				</colgroup>
				<thead class="text-gray-400 uppercase tracking-wide">
					<tr class="border-b">
						<th class="text-left font-medium px-3 py-1.5">#</th>
						<th class="text-left font-medium px-3 py-1.5">Step</th>
						<th class="text-left font-medium px-3 py-1.5">Timeline</th>
						<th class="text-right font-medium px-3 py-1.5">Latency</th>
						<th class="text-right font-medium px-3 py-1.5">Tokens</th>
						<th class="text-right font-medium px-3 py-1.5">Cost</th>
					</tr>
				</thead>
				<tbody>
					<template v-for="(s, si) in steps" :key="s.name">
						<tr
							class="border-b border-gray-50 cursor-pointer hover:bg-gray-50"
							:class="s.error_code ? 'bg-red-50/60' : (si % 2 ? 'bg-gray-50/70' : 'bg-white')"
							@click="toggle(s.name)"
						>
							<td class="px-3 py-1.5 text-gray-400">{{ s.step_index }}</td>
							<td class="px-3 py-1.5">
								<div class="flex items-center gap-1.5 min-w-0">
									<Icon :icon="open.has(s.name) ? 'lucide:chevron-down' : 'lucide:chevron-right'" class="w-3 h-3 text-gray-400 shrink-0" />
									<span class="rounded px-1.5 py-0.5 font-mono text-[10px] shrink-0" :class="KIND_PILLS[s.step_kind] || KIND_PILLS.model_call">{{ (s.step_kind || 'step').replace('_', ' ') }}</span>
									<span class="font-mono text-gray-700 truncate">{{ kindLabel(s) }}</span>
									<span v-if="s.error_code" class="rounded px-1.5 text-[10px] bg-red-100 text-red-700 shrink-0">{{ s.error_code }}</span>
									<span v-if="s.child_runs && s.child_runs.length" class="rounded px-1.5 text-[10px] bg-indigo-50 text-indigo-700 shrink-0">+{{ s.child_runs.length }} run</span>
								</div>
							</td>
							<td class="px-3 py-1.5">
								<div class="relative h-2.5 bg-gray-100 rounded">
									<div
										v-if="s.latency_ms"
										class="absolute h-2.5 rounded"
										:class="barTone(s)"
										:style="{ left: bar(s).left + '%', width: Math.max(bar(s).width, 0.5) + '%' }"
										:title="fmtMs(s.latency_ms)"
									></div>
								</div>
							</td>
							<td class="px-3 py-1.5 text-right text-gray-700">{{ s.latency_ms ? fmtMs(s.latency_ms) : "" }}</td>
							<td class="px-3 py-1.5 text-right text-gray-500">{{ (s.prompt_tokens || 0) + (s.completion_tokens || 0) ? fmtNum((s.prompt_tokens || 0) + (s.completion_tokens || 0)) : "" }}</td>
							<td class="px-3 py-1.5 text-right text-gray-500">{{ s.cost ? fmtCost(s.cost) : "" }}</td>
						</tr>
						<tr v-if="open.has(s.name)" class="border-b bg-gray-50/60">
							<td></td>
							<td colspan="5" class="px-3 py-2 space-y-2">
								<div v-if="s.error_message">
									<div class="text-[11px] uppercase text-red-500 mb-0.5">Error</div>
									<pre class="text-xs text-red-800 whitespace-pre-wrap bg-red-50 rounded p-2 max-h-48 overflow-auto">{{ s.error_message }}</pre>
								</div>
								<div v-if="s.content && s.role !== 'system'">
									<div class="text-[11px] uppercase text-gray-400 mb-0.5">{{ s.role === "user" ? "Input" : s.role === "assistant" ? "Output" : "Narration" }}</div>
									<pre class="text-xs text-gray-700 whitespace-pre-wrap bg-white border rounded p-2 max-h-72 overflow-auto">{{ s.content }}</pre>
								</div>
								<div v-if="s.role === 'system'" class="text-xs text-gray-400">System prompt shown above.</div>
								<div v-for="(c, ci) in s.tool_calls" :key="ci" class="border rounded bg-white p-2">
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
								<div v-if="s.child_runs && s.child_runs.length" class="space-y-1">
									<div class="text-[11px] uppercase text-gray-400">Runs this step started</div>
									<router-link
										v-for="child in s.child_runs"
										:key="child.run.name"
										:to="`/processa/runs/${child.run.name}`"
										class="flex items-center gap-2 text-xs text-blue-700 hover:underline"
									>
										<Icon icon="lucide:corner-down-right" class="w-3 h-3 text-gray-400" />
										<span class="font-mono">{{ child.run.name }}</span>
										<span class="text-gray-500">{{ child.run.agent_configuration || child.run.bpmn_label }}</span>
										<Badge :theme="child.run.status === 'Success' ? 'green' : 'red'" size="sm">{{ child.run.status }}</Badge>
										<span class="text-gray-500">{{ fmtNum(child.rollup.total_tokens) }} tokens, {{ fmtCost(child.rollup.estimated_cost) }}</span>
									</router-link>
								</div>
								<div v-if="!s.content && !s.tool_calls.length && !s.error_message && s.role !== 'system'" class="text-xs text-gray-400">Nothing recorded for this step.</div>
							</td>
						</tr>
					</template>
				</tbody>
			</table>
			<div v-if="unplacedChildren.length" class="px-4 py-2 border-t text-xs">
				<div class="text-gray-400 uppercase text-[11px] mb-1">Runs started during this run</div>
				<router-link v-for="child in unplacedChildren" :key="child.run.name" :to="`/processa/runs/${child.run.name}`" class="block text-blue-700 hover:underline font-mono">{{ child.run.name }} <span class="text-gray-500 font-sans">{{ child.run.agent_configuration || child.run.bpmn_label }}</span></router-link>
			</div>
		</div>

		<div class="bg-white border rounded-lg px-4 py-3">
			<div class="flex items-center gap-2 text-xs text-gray-600 mb-1">
				<span class="font-semibold">Final output</span>
				<span v-if="run.goal_completion" :class="GOAL_TONES[run.goal_completion] || 'text-gray-400'">{{ run.goal_completion }}</span>
				<span v-if="run.no_terminal_tool" class="text-amber-700 bg-amber-50 rounded px-1.5" title="the model answered in plain text instead of calling its terminal tool">no terminal tool</span>
				<span v-if="run.completion_basis" class="text-gray-400 truncate" :title="run.completion_basis">{{ run.completion_basis }}</span>
			</div>
			<pre class="text-xs text-gray-700 whitespace-pre-wrap max-h-96 overflow-auto">{{ run.final_output || "(empty)" }}</pre>
		</div>
	</div>
</template>

<script setup>
import { Badge } from "frappe-ui"
import { Icon } from "@iconify/vue"
import { computed, ref, watch } from "vue"
import { RouterLink } from "vue-router"
import { dayjs } from "@/dayjs"
import { fmtCost, fmtMs, fmtNum, prettyJson } from "@/utils/runFormat"

const props = defineProps({
	run: { type: Object, required: true },
	steps: { type: Array, default: () => [] },
	unplacedChildren: { type: Array, default: () => [] },
})

const GOAL_TONES = { Achieved: "text-green-700", "Not Achieved": "text-red-700" }
const KIND_PILLS = {
	prompt: "bg-gray-100 text-gray-600",
	model_call: "bg-teal-50 text-teal-700",
	tool_turn: "bg-amber-50 text-amber-700",
	sub_call: "bg-indigo-50 text-indigo-700",
}

// A failed step is the one the reader came for, so it starts open.
const open = ref(new Set())
watch(
	() => props.steps,
	(rows) => {
		open.value = new Set((rows || []).filter((s) => s.error_code).map((s) => s.name))
	},
	{ immediate: true },
)

function toggle(name) {
	const next = new Set(open.value)
	next.has(name) ? next.delete(name) : next.add(name)
	open.value = next
}

function setAll(on) {
	open.value = on ? new Set(props.steps.map((s) => s.name)) : new Set()
}

const systemPrompt = computed(() => {
	const first = props.steps.find((s) => s.role === "system")
	return (first && first.content) || ""
})

const latencyTotal = computed(() => props.steps.reduce((a, s) => a + (s.latency_ms || 0), 0) || 1)
const slowest = computed(() =>
	[...props.steps].filter((s) => s.latency_ms > 0).sort((a, b) => b.latency_ms - a.latency_ms).slice(0, 3),
)

// Steps recorded before timestamps existed carry a window rebuilt from
// latency, so the bars show sequence, not the clock.
const timed = computed(() => props.steps.filter((s) => s.latency_ms > 0))
const hasClock = computed(() => timed.value.length > 0 && timed.value.every((s) => s.started_at && s.ended_at))
const window_ = computed(() => {
	if (!hasClock.value) return null
	const starts = timed.value.map((s) => dayjs(s.started_at).valueOf())
	const ends = timed.value.map((s) => dayjs(s.ended_at).valueOf())
	const min = Math.min(...starts)
	return { min, span: Math.max(Math.max(...ends) - min, 1) }
})
const timelineLabel = computed(() =>
	hasClock.value
		? `Timeline: each bar sits where the step ran, over ${fmtMs(window_.value.span)} of wall clock`
		: "Timeline: bars show each step's share of the run's latency, in step order",
)

function bar(s) {
	if (window_.value) {
		const left = ((dayjs(s.started_at).valueOf() - window_.value.min) / window_.value.span) * 100
		const width = ((dayjs(s.ended_at).valueOf() - dayjs(s.started_at).valueOf()) / window_.value.span) * 100
		return { left, width }
	}
	let before = 0
	for (const other of props.steps) {
		if (other.name === s.name) break
		before += other.latency_ms || 0
	}
	return { left: pct(before, latencyTotal.value), width: pct(s.latency_ms, latencyTotal.value) }
}

function pct(a, b) {
	return b ? (a * 100) / b : 0
}

function barTone(s) {
	if (s.error_code || (s.tool_calls || []).some((c) => c.status !== "Success")) return "bg-red-500"
	if (s.step_kind === "sub_call") return "bg-indigo-400"
	if (s.step_kind === "tool_turn") return "bg-amber-400"
	return "bg-teal-500"
}

function kindLabel(s) {
	if (s.sub_call) return `${s.sub_call.tool} via ${s.sub_call.model}`
	if (s.tool_names && s.tool_names.length) return s.tool_names.join(", ")
	if (s.role === "assistant") return "model call"
	return s.role
}

function hasValue(v) {
	if (v == null || v === "") return false
	if (typeof v === "object") return Object.keys(v).length > 0
	return v !== "{}"
}
</script>
