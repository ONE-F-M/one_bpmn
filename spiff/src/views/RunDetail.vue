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

			<!-- Tree -->
			<div v-if="tab === 'tree'" class="bg-white border rounded-lg p-3">
				<RunTree :node="tree" />
			</div>

			<!-- Conversation: every turn, opened one at a time down to the
			     steps and the runs those steps delegated. -->
			<div v-else class="bg-white border rounded-lg overflow-hidden">
				<div v-if="run && run.parent_run" class="px-4 py-2 border-b text-xs text-gray-500">
					This run was started by a tool call inside
					<RouterLink :to="`/processa/runs/${run.parent_run}`" class="font-mono text-blue-600 hover:underline">{{ run.parent_run }}</RouterLink>.
					It is not a turn of the conversation; open that run to read the conversation it belongs to.
				</div>
				<div v-else class="px-4 py-2 border-b text-xs text-gray-500">
					Every turn on this instance, oldest first, with a bar for the time it took and the waiting between turns collapsed. Open one to read its steps; a step that handed work
					to another agent opens that agent's run underneath it.
				</div>
				<table class="w-full text-xs">
					<thead class="text-gray-400 uppercase tracking-wide">
						<tr class="border-b">
							<th class="text-left font-medium px-4 py-1.5 w-16">Turn</th>
							<th class="text-left font-medium px-3 py-1.5">Started</th>
							<th class="text-left font-medium px-3 py-1.5">Run</th>
							<th class="text-left font-medium px-3 py-1.5">Status</th>
							<th class="text-left font-medium px-3 py-1.5 w-56">Timeline</th>
							<th class="text-right font-medium px-3 py-1.5">Latency</th>
							<th class="text-right font-medium px-3 py-1.5">Tokens</th>
							<th class="text-right font-medium px-3 py-1.5">Cost</th>
							<th class="text-left font-medium px-3 py-1.5">Answer</th>
						</tr>
					</thead>
					<tbody class="divide-y">
						<template v-for="(sib, i) in detail.siblings" :key="sib.name">
							<tr v-if="waterfall[i] && waterfall[i].gap" class="text-gray-400">
								<td></td>
								<td colspan="7" class="px-3 py-0.5">
									<div class="flex items-center gap-2">
										<div class="h-px w-6 bg-gray-200"></div>
										<span class="text-[10px]">{{ fmtMs(waterfall[i].gap) }} idle</span>
										<div class="h-px flex-1 bg-gray-200"></div>
									</div>
								</td>
							</tr>
							<tr
								class="cursor-pointer hover:bg-gray-200"
								:class="sib.name === run.name ? 'bg-blue-50/60' : i % 2 ? 'bg-gray-100' : 'bg-white'"
								@click="toggleTurn(sib.name)"
							>
								<td class="px-4 py-1.5 text-gray-500">
									<span class="inline-flex items-center gap-1">
										<Icon
											:icon="openTurns.has(sib.name) ? 'lucide:chevron-down' : 'lucide:chevron-right'"
											class="w-3 h-3 text-gray-400"
										/>
										{{ i + 1 }}
									</span>
								</td>
								<td class="px-3 py-1.5 text-gray-600 whitespace-nowrap">{{ fmtDateTime(sib.started_at) }}</td>
								<td class="px-3 py-1.5">
									<div class="font-mono text-blue-700">{{ sib.name }}</div>
									<div class="text-gray-400">{{ sib.agent_configuration || sib.bpmn_label }}</div>
								</td>
								<td class="px-3 py-1.5"><Badge :theme="STATUS_THEMES[sib.status] || 'gray'" size="sm">{{ sib.status }}</Badge></td>
								<td class="px-3 py-1.5">
									<div class="h-2.5 bg-gray-100 rounded relative">
										<div
											class="absolute h-2.5 rounded"
											:class="sib.status === 'Error' ? 'bg-red-300' : 'bg-teal-300'"
											:style="{ width: (waterfall[i] ? waterfall[i].width : 0) + '%' }"
											:title="`${fmtMs(sib.agent_latency_ms)} of the longest turn`"
										></div>
									</div>
								</td>
								<td class="px-3 py-1.5 text-right text-gray-700">{{ fmtMs(sib.agent_latency_ms) }}</td>
								<td class="px-3 py-1.5 text-right text-gray-700">{{ fmtNum(sib.total_tokens) }}</td>
								<td class="px-3 py-1.5 text-right text-gray-700">{{ fmtCost(sib.estimated_cost) }}</td>
								<td class="px-3 py-1.5 text-gray-600 max-w-md truncate" :title="sib.final_output">{{ sib.final_output || "" }}</td>
							</tr>
							<tr v-if="openTurns.has(sib.name)">
								<td colspan="9" class="px-4 py-2 bg-gray-50/60">
									<div v-if="turnLoading.has(sib.name)" class="text-xs text-gray-500 py-2">Loading steps…</div>
									<ErrorMessage v-else-if="turnErrors[sib.name]" :message="turnErrors[sib.name]" />
									<div v-else-if="turnFor(sib.name)">
										<div class="flex items-center gap-3 text-xs text-gray-500 mb-2">
											<span>Own cost {{ fmtCost(sib.estimated_cost) }}</span>
											<span v-if="turnHasChildren(sib.name)">
												Including delegated work {{ fmtCost(turnFor(sib.name).rollup.estimated_cost) }},
												{{ fmtNum(turnFor(sib.name).rollup.total_tokens) }} tokens
											</span>
											<RouterLink
												v-if="sib.name !== run.name"
												class="text-blue-600 hover:underline ml-auto"
												:to="`/processa/runs/${sib.name}`"
											>
												Open this turn on its own page
											</RouterLink>
										</div>
										<TurnDetail
											:run="turnFor(sib.name).run"
											:steps="turnFor(sib.name).steps"
											:unplaced-children="turnFor(sib.name).unplaced_children || []"
										/>
									</div>
								</td>
							</tr>
						</template>
					</tbody>
				</table>
			</div>

		</div>
	</div>
</template>

<script setup>
import { Badge, Button, ErrorMessage, frappeRequest } from "frappe-ui"
import { Icon } from "@iconify/vue"
import { computed, onMounted, reactive, ref, watch } from "vue"
import { RouterLink, useRoute, useRouter } from "vue-router"
import { dayjs } from "@/dayjs"
import RunTree from "@/components/insights/RunTree.vue"
import TurnDetail from "@/components/insights/TurnDetail.vue"
import { fmtCost, fmtMs, fmtNum } from "@/utils/runFormat"

const STATUS_THEMES = { Success: "green", Error: "red", Running: "blue", Suspended: "orange" }
const GOAL_TONES = { Achieved: "text-green-700", "Not Achieved": "text-red-700" }

const route = useRoute()
const router = useRouter()
const loading = ref(true)
const error = ref("")
const detail = ref({})
const tab = ref("conversation")
const creatingCase = ref(false)

// A turn's steps are fetched when it is opened: a twenty turn conversation
// would otherwise load twenty trees nobody asked for.
const openTurns = ref(new Set())
const turns = reactive({})
const turnLoading = ref(new Set())
const turnErrors = reactive({})

async function toggleTurn(name) {
	const next = new Set(openTurns.value)
	if (next.has(name)) {
		next.delete(name)
		openTurns.value = next
		syncTurnInUrl()
		return
	}
	next.add(name)
	openTurns.value = next
	syncTurnInUrl()
	if (turns[name]) return
	const busy = new Set(turnLoading.value)
	busy.add(name)
	turnLoading.value = busy
	try {
		turns[name] = await frappeRequest({
			url: "/api/method/one_bpmn.api.insights_api.get_turn_steps",
			params: { run_name: name },
		})
		delete turnErrors[name]
	} catch (e) {
		turnErrors[name] = e.message || String(e)
	} finally {
		const done = new Set(turnLoading.value)
		done.delete(name)
		turnLoading.value = done
	}
}

// The open turn rides in the query string so a turn can be linked to.
function syncTurnInUrl() {
	const open = [...openTurns.value]
	const turn = open.length ? open[open.length - 1] : undefined
	router.replace({ query: { ...route.query, turn } })
}

// The page already holds its own run's tree, so the turn it arrived on does
// not need fetching to render like every other turn.
function turnFor(name) {
	if (run.value && name === run.value.name) {
		return { run: run.value, steps: steps.value, unplaced_children: tree.value.unplaced_children || [], rollup: tree.value.rollup || {} }
	}
	return turns[name]
}

function turnHasChildren(name) {
	const t = turnFor(name)
	if (!t) return false
	const inSteps = (t.steps || []).some((step) => (step.child_runs || []).length)
	return inSteps || (t.unplaced_children || []).length > 0
}

const run = computed(() => detail.value.run || null)
const tree = computed(() => detail.value.tree || { steps: [], unplaced_children: [] })
const steps = computed(() => tree.value.steps || [])
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
	{ key: "conversation", label: "Conversation", count: (detail.value.siblings || []).length },
	{ key: "tree", label: "Tree", count: tree.value.rollup ? tree.value.rollup.runs : null },
])

// Bar width is the time a turn took, against the longest turn. The wait
// between two turns is collapsed to a label, since a person thinking for
// four minutes would otherwise squeeze every turn into a hairline.
const waterfall = computed(() => {
	const rows = detail.value.siblings || []
	const longest = Math.max(...rows.map((r) => r.agent_latency_ms || r.duration_ms || 0), 1)
	let previousEnd = null
	return rows.map((r) => {
		const duration = r.agent_latency_ms || r.duration_ms || 0
		const start = r.started_at ? dayjs(r.started_at).valueOf() : null
		const gap = start && previousEnd && start > previousEnd ? start - previousEnd : 0
		previousEnd = r.ended_at ? dayjs(r.ended_at).valueOf() : start
		return {
			key: r.name,
			name: r.name,
			status: r.status,
			duration,
			cost: r.estimated_cost,
			gap,
			left: 0,
			width: Math.max((duration / longest) * 100, 1),
		}
	})
})


function fmtDateTime(v) {
	return v ? dayjs(v).format("DD MMM YYYY HH:mm:ss") : ""
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
onMounted(async () => {
	await load()
	// The run you arrived on is the turn you came to read, so it starts open.
	if (run.value) openTurns.value = new Set([run.value.name])
	// A link that names a turn opens on that turn, so a turn can be sent to
	// somebody and read where the sender was reading.
	const turn = route.query.turn
	if (turn) {
		tab.value = "conversation"
		toggleTurn(turn)
	}
})
</script>
