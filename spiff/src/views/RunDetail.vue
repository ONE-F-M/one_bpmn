<template>
	<div class="h-full flex flex-col bg-gray-50">
		<header class="bg-white border-b px-6 py-3 shrink-0">
			<div class="flex items-center gap-3 flex-wrap">
				<Button icon-left="arrow-left" variant="ghost" size="sm" @click="$router.push('/processa/runs')">Runs</Button>
				<div class="h-5 w-px bg-gray-200"></div>
				<template v-if="run">
					<h1 class="text-base font-bold text-gray-900">{{ run.agent_configuration || run.bpmn_label || run.bpmn_id }}</h1>
					<span class="font-mono text-sm text-gray-500">{{ run.name }}</span>
					<Badge :theme="STATUS_THEMES[run.status] || 'gray'" size="lg">{{ run.status }}</Badge>
					<span v-if="run.model || detail.agent_model" class="text-xs font-mono text-gray-500" :title="run.model ? 'model recorded on the run' : 'model the agent configuration names today'">
						{{ run.model || detail.agent_model }}
					</span>
					<span v-if="run.origin === 'eval'" class="text-xs text-purple-700 bg-purple-50 rounded px-1.5">eval</span>
				</template>
				<div class="ml-auto flex items-center gap-2">
					<Button size="sm" :loading="creatingCase" :disabled="!run || !['Success', 'Error'].includes(run.status)" @click="createEvalCase">Create eval case</Button>
					<a v-if="run" :href="`/app/ai-agent-run/${run.name}`" target="_blank" class="text-sm text-blue-600 hover:underline">Open in Desk</a>
				</div>
			</div>
			<div v-if="run" class="flex items-center gap-6 mt-2 text-[12px] text-gray-500 flex-wrap">
				<span v-if="detail.instance" class="flex items-center gap-1">
					<span class="font-bold text-gray-600">Instance</span>
					<router-link :to="`/processa/instances/${detail.instance.name}`" class="font-mono text-blue-600 hover:underline">{{ detail.instance.name }}</router-link>
					<span class="text-gray-400">{{ detail.instance.process_model }}</span>
				</span>
				<span v-if="detail.conversation" class="flex items-center gap-1">
					<span class="font-bold text-gray-600">Conversation</span>
					<a :href="`/app/chat-conversation/${detail.conversation.name}`" target="_blank" class="text-blue-600 hover:underline">
						{{ detail.conversation.agent_mode || "" }} {{ detail.conversation.name }}
					</a>
				</span>
				<span class="flex items-center gap-1">
					<span class="font-bold text-gray-600">User</span>
					<span class="text-gray-700">{{ detail.instance?.initiated_by || "" }}</span>
				</span>
				<span class="flex items-center gap-1">
					<span class="font-bold text-gray-600">Started</span>
					<span class="font-mono text-gray-700">{{ fmtDateTime(run.started_at) }}</span>
				</span>
				<span v-if="run.parent_run" class="flex items-center gap-1">
					<span class="font-bold text-gray-600">Parent run</span>
					<router-link :to="`/processa/runs/${run.parent_run}`" class="font-mono text-blue-600 hover:underline">{{ run.parent_run }}</router-link>
				</span>
				<span v-if="run.eval_case" class="flex items-center gap-1">
					<span class="font-bold text-gray-600">Eval case</span>
					<a :href="`/app/ai-eval-case/${run.eval_case}`" target="_blank" class="font-mono text-blue-600 hover:underline">{{ run.eval_case }}</a>
				</span>
				<span v-if="run.provider || run.backend" class="text-gray-400">{{ run.provider }} {{ run.backend }}</span>
			</div>
		</header>

		<div v-if="loading" class="flex-1 flex items-center justify-center text-sm text-gray-500">Loading run</div>
		<ErrorMessage v-else-if="error" :message="error" class="m-6" />

		<div v-else-if="run" class="flex-1 overflow-auto px-6 py-4 space-y-4">
			<div v-if="run.error_code" class="bg-red-50 border border-red-200 text-red-800 text-sm rounded-lg px-4 py-3">
				<span class="font-semibold font-mono">{{ run.error_code }}</span>
				<pre v-if="run.error_message" class="mt-1 whitespace-pre-wrap text-xs text-red-700">{{ run.error_message }}</pre>
			</div>

			<div class="grid grid-cols-2 md:grid-cols-4 xl:grid-cols-8 gap-3">
				<div v-for="m in metrics" :key="m.label" class="bg-white border rounded-lg px-3 py-2" :title="m.title || ''">
					<div class="text-xs text-gray-500">{{ m.label }}</div>
					<div class="text-base font-semibold text-gray-900 truncate" :class="m.tone">{{ m.value }}</div>
					<div v-if="m.sub" class="text-xs text-gray-400 truncate">{{ m.sub }}</div>
				</div>
			</div>

			<nav class="flex gap-1 bg-gray-100 rounded-lg p-1 w-fit">
				<button
					v-for="t in tabs"
					:key="t.key"
					class="px-3 py-1.5 text-sm rounded-md transition-colors"
					:class="tab === t.key ? 'bg-white shadow-sm font-medium text-gray-900' : 'text-gray-600 hover:text-gray-900'"
					@click="tab = t.key"
				>
					{{ t.label }} <span v-if="t.count != null" class="ml-1 text-xs text-gray-400">{{ t.count }}</span>
				</button>
			</nav>

			<!-- Steps -->
			<template v-if="tab === 'steps'">
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

				<details v-if="detail.system_prompt" class="bg-white border rounded-lg px-4 py-2">
					<summary class="text-xs text-gray-600 cursor-pointer">
						System prompt <span class="text-gray-400">{{ detail.system_prompt.split("\n")[0].slice(0, 120) }}</span>
						<span v-if="run.prompt_hash" class="font-mono text-gray-400 ml-2">{{ run.prompt_hash.slice(0, 12) }}</span>
					</summary>
					<pre class="mt-2 text-xs text-gray-700 whitespace-pre-wrap max-h-96 overflow-auto">{{ detail.system_prompt }}</pre>
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
							<template v-for="s in steps" :key="s.name">
								<tr class="border-b border-gray-50 cursor-pointer hover:bg-gray-50" :class="s.error_code ? 'bg-red-50/60' : ''" @click="toggle(s.name)">
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
					<div v-if="tree.unplaced_children && tree.unplaced_children.length" class="px-4 py-2 border-t text-xs">
						<div class="text-gray-400 uppercase text-[11px] mb-1">Runs started during this run</div>
						<router-link v-for="child in tree.unplaced_children" :key="child.run.name" :to="`/processa/runs/${child.run.name}`" class="block text-blue-700 hover:underline font-mono">{{ child.run.name }} <span class="text-gray-500 font-sans">{{ child.run.agent_configuration || child.run.bpmn_label }}</span></router-link>
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
			</template>

			<!-- Tree -->
			<div v-else-if="tab === 'tree'" class="bg-white border rounded-lg p-3">
				<RunTree :node="tree" />
			</div>

			<!-- Conversation -->
			<div v-else class="bg-white border rounded-lg overflow-hidden">
				<div class="px-4 py-2 border-b text-xs text-gray-500">
					Every top-level run on this instance, in the order it happened. The run you are reading is highlighted.
				</div>
				<table class="w-full text-xs">
					<thead class="text-gray-400 uppercase tracking-wide">
						<tr class="border-b">
							<th class="text-left font-medium px-4 py-1.5">Turn</th>
							<th class="text-left font-medium px-3 py-1.5">Started</th>
							<th class="text-left font-medium px-3 py-1.5">Run</th>
							<th class="text-left font-medium px-3 py-1.5">Status</th>
							<th class="text-right font-medium px-3 py-1.5">Latency</th>
							<th class="text-right font-medium px-3 py-1.5">Tokens</th>
							<th class="text-right font-medium px-3 py-1.5">Cost</th>
							<th class="text-left font-medium px-3 py-1.5">Answer</th>
						</tr>
					</thead>
					<tbody class="divide-y">
						<tr
							v-for="(sib, i) in detail.siblings"
							:key="sib.name"
							class="cursor-pointer hover:bg-gray-50"
							:class="sib.name === run.name ? 'bg-blue-50/60' : ''"
							@click="$router.push(`/processa/runs/${sib.name}`)"
						>
							<td class="px-4 py-1.5 text-gray-500">{{ i + 1 }}</td>
							<td class="px-3 py-1.5 text-gray-600 whitespace-nowrap">{{ fmtDateTime(sib.started_at) }}</td>
							<td class="px-3 py-1.5">
								<div class="font-mono text-blue-700">{{ sib.name }}</div>
								<div class="text-gray-400">{{ sib.agent_configuration || sib.bpmn_label }}</div>
							</td>
							<td class="px-3 py-1.5"><Badge :theme="STATUS_THEMES[sib.status] || 'gray'" size="sm">{{ sib.status }}</Badge></td>
							<td class="px-3 py-1.5 text-right text-gray-700">{{ fmtMs(sib.agent_latency_ms) }}</td>
							<td class="px-3 py-1.5 text-right text-gray-700">{{ fmtNum(sib.total_tokens) }}</td>
							<td class="px-3 py-1.5 text-right text-gray-700">{{ fmtCost(sib.estimated_cost) }}</td>
							<td class="px-3 py-1.5 text-gray-600 max-w-md truncate" :title="sib.final_output">{{ sib.final_output || "" }}</td>
						</tr>
					</tbody>
				</table>
			</div>
		</div>
	</div>
</template>

<script setup>
import { Badge, Button, ErrorMessage, frappeRequest } from "frappe-ui"
import { Icon } from "@iconify/vue"
import { computed, onMounted, ref, watch } from "vue"
import { useRoute } from "vue-router"
import { dayjs } from "@/dayjs"
import RunTree from "@/components/insights/RunTree.vue"
import { fmtCost, fmtMs, fmtNum, prettyJson } from "@/utils/runFormat"

const STATUS_THEMES = { Success: "green", Error: "red", Running: "blue", Suspended: "orange" }
const GOAL_TONES = { Achieved: "text-green-700", "Not Achieved": "text-red-700" }
const KIND_PILLS = {
	prompt: "bg-gray-100 text-gray-600",
	model_call: "bg-teal-50 text-teal-700",
	tool_turn: "bg-amber-50 text-amber-700",
	sub_call: "bg-indigo-50 text-indigo-700",
}

const route = useRoute()
const loading = ref(true)
const error = ref("")
const detail = ref({})
const tab = ref("steps")
const open = ref(new Set())
const creatingCase = ref(false)

const run = computed(() => detail.value.run || null)
const tree = computed(() => detail.value.tree || { steps: [], unplaced_children: [] })
const steps = computed(() => tree.value.steps || [])
const latencyTotal = computed(() => steps.value.reduce((a, s) => a + (s.latency_ms || 0), 0) || 1)
const slowest = computed(() => [...steps.value].filter((s) => s.latency_ms > 0).sort((a, b) => b.latency_ms - a.latency_ms).slice(0, 3))

// A real timeline needs a start and end on every timed step. Steps recorded
// before those existed carry a window rebuilt from their latency, which is a
// sequence, not the clock; the label says which one the bars show.
const timed = computed(() => steps.value.filter((s) => s.latency_ms > 0))
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
	for (const other of steps.value) {
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

const metrics = computed(() => {
	const r = run.value
	if (!r) return []
	const roll = tree.value.rollup || {}
	const treeCost = roll.runs > 1 ? `tree ${fmtCost(roll.estimated_cost)}` : ""
	return [
		{ label: "Agent latency", value: fmtMs(r.agent_latency_ms), sub: "sum of step latencies" },
		{ label: "Wall clock", value: fmtMs(r.duration_ms), sub: r.human_wait_ms ? `waited on people ${fmtMs(r.human_wait_ms)}` : "" },
		{ label: "Steps", value: steps.value.length, sub: `${steps.value.filter((s) => s.step_kind === "tool_turn").length} tool turns` },
		{ label: "Tool calls", value: steps.value.reduce((a, s) => a + (s.tool_calls || []).length, 0), sub: `${steps.value.filter((s) => s.error_code).length} failed steps` },
		{ label: "Tokens in", value: fmtNum(r.total_prompt_tokens), sub: `cache read ${fmtNum(r.total_cache_read_tokens)}` },
		{ label: "Tokens out", value: fmtNum(r.total_completion_tokens), sub: `cache write ${fmtNum(r.total_cache_write_tokens)}` },
		{ label: "Cost", value: fmtCost(r.estimated_cost), sub: treeCost, title: "this run's own model calls; tree adds the runs its tools started" },
		{ label: "Goal", value: r.goal_completion || "Unknown", sub: r.completion_basis || "", tone: GOAL_TONES[r.goal_completion] || "" },
	]
})

const tabs = computed(() => [
	{ key: "steps", label: "Steps", count: steps.value.length },
	{ key: "tree", label: "Tree", count: tree.value.rollup ? tree.value.rollup.runs : null },
	{ key: "conversation", label: "Conversation", count: (detail.value.siblings || []).length },
])

function fmtDateTime(v) {
	return v ? dayjs(v).format("DD MMM YYYY HH:mm:ss") : ""
}

function toggle(name) {
	const next = new Set(open.value)
	next.has(name) ? next.delete(name) : next.add(name)
	open.value = next
}

function setAll(on) {
	open.value = on ? new Set(steps.value.filter((s) => s.role !== "system").map((s) => s.name)) : new Set()
}

async function load() {
	loading.value = true
	error.value = ""
	try {
		detail.value = await frappeRequest({
			url: "/api/method/one_bpmn.api.insights_api.get_run_detail",
			method: "POST",
			params: { run_name: route.params.run },
		})
		open.value = new Set(steps.value.filter((s) => s.error_code).map((s) => s.name))
		tab.value = "steps"
	} catch (e) {
		error.value = e.message || String(e)
	} finally {
		loading.value = false
	}
}

async function createEvalCase() {
	creatingCase.value = true
	try {
		const name = await frappeRequest({
			url: "/api/method/one_bpmn.agents.eval_case_factory.create_eval_case_from_run",
			method: "POST",
			params: { run_name: run.value.name },
		})
		if (name) window.open(`/app/ai-eval-case/${name}`, "_blank")
	} catch (e) {
		error.value = e.message || String(e)
	} finally {
		creatingCase.value = false
	}
}

watch(() => route.params.run, () => route.params.run && load())
onMounted(load)
</script>
