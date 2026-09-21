<template>
	<div class="h-full flex flex-col bg-gray-50">
		<header class="bg-white border-b px-6 py-4">
			<div class="flex items-center justify-between">
				<div>
					<h1 class="text-xl font-semibold text-gray-900">Runs</h1>
					<p class="text-xs text-gray-500 mt-0.5">
						Every agent run, newest first. Open one to read it step by step.
					</p>
				</div>
				<Button :loading="loading" @click="load()">Refresh</Button>
			</div>
		</header>

		<div class="bg-white px-6 py-3 border-b flex flex-wrap gap-3 items-center">
			<!-- Autocomplete's popover is hardcoded w-full, so the width comes
			     from the wrapper, the same way UserFilter does it. -->
			<div class="w-52">
				<Autocomplete
					v-model="agentOption"
					:options="agentOptions"
					:compare-fn="compareOption"
					placeholder="All agents"
				/>
			</div>
			<FormControl type="select" v-model="filters.status" :options="statusOptions" class="w-36" @change="load()" />
			<FormControl type="select" v-model="filters.origin" :options="ORIGINS" class="w-32" @change="reloadAll()" />
			<FormControl type="select" v-model="filters.user" :options="userOptions" class="w-52" @change="load()" />
			<FormControl type="select" v-model="filters.model" :options="modelOptions" class="w-48" @change="load()" />
			<FormControl type="date" v-model="filters.from_date" class="w-36" @change="load()" />
			<FormControl type="date" v-model="filters.to_date" class="w-36" @change="load()" />
			<FormControl
				type="checkbox"
				v-model="filters.errors_only"
				label="Errors only"
				class="whitespace-nowrap"
				@change="load()"
			/>
			<FormControl type="text" v-model="filters.search" placeholder="Search run, instance, user, answer" class="w-64" @change="load()" />
			<div class="flex items-center gap-2 ml-auto">
				<FormControl type="select" v-model="order" :options="ORDERS" class="w-40" @change="load()" />
				<FormControl type="select" v-model="pageLength" :options="PAGE_SIZES" class="w-20" @change="load()" />
			</div>
		</div>

		<div v-if="filters.instance" class="mx-6 mt-3 flex items-center gap-2 text-sm text-gray-600">
			Showing runs of instance
			<router-link :to="`/processa/instances/${filters.instance}`" class="font-mono text-blue-600 hover:underline">{{ filters.instance }}</router-link>
			<Button size="sm" variant="ghost" @click="filters.instance = ''; load()">Clear</Button>
		</div>

		<ErrorMessage v-if="error" :message="error" class="mx-6 mt-3" />

		<div class="flex-1 overflow-auto">
			<div class="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-6 gap-3 px-6 pt-4">
				<div v-for="tile in tiles" :key="tile.label" class="bg-white border rounded-lg px-4 py-3">
					<div class="text-xs text-gray-500">{{ tile.label }}</div>
					<div class="text-xl font-semibold mt-0.5" :class="tile.tone || 'text-gray-900'">{{ tile.value }}</div>
					<div class="text-xs text-gray-400 mt-0.5">{{ tile.sub }}</div>
				</div>
			</div>

			<div v-if="!loading && !runs.length" class="p-10 text-center text-sm text-gray-500">
				No runs match those filters.
			</div>
			<table v-else class="w-full text-sm mt-4">
				<thead class="bg-gray-50 text-xs uppercase tracking-wide text-gray-500 sticky top-0">
					<tr>
						<th class="text-left font-medium px-6 py-2">Started</th>
						<th class="text-left font-medium px-3 py-2">Agent</th>
						<th class="text-left font-medium px-3 py-2">Run</th>
						<th class="text-left font-medium px-3 py-2">User</th>
						<th class="text-left font-medium px-3 py-2">Status</th>
						<th class="text-right font-medium px-3 py-2">Steps</th>
						<th class="text-right font-medium px-3 py-2">Tools</th>
						<th class="text-right font-medium px-3 py-2">Latency</th>
						<th class="text-right font-medium px-3 py-2">Tokens</th>
						<th class="text-right font-medium px-3 py-2">Cost</th>
						<th class="text-left font-medium px-3 py-2">Goal</th>
					</tr>
				</thead>
				<tbody class="divide-y bg-white">
					<tr
						v-for="r in runs"
						:key="r.name"
						class="hover:bg-gray-50 cursor-pointer"
						@click="$router.push(`/processa/runs/${r.name}`)"
					>
						<td class="px-6 py-2 text-gray-600 whitespace-nowrap">{{ fmtDate(r.started_at) }}</td>
						<td class="px-3 py-2">
							<div class="text-gray-900">{{ r.agent_configuration || r.bpmn_label || r.bpmn_id }}</div>
							<div class="text-xs text-gray-400 font-mono">{{ r.model || "" }}</div>
						</td>
						<td class="px-3 py-2">
							<div class="font-mono text-blue-600">{{ r.name }}</div>
							<router-link
								v-if="r.instance"
								:to="`/processa/instances/${r.instance}`"
								class="text-xs text-gray-400 font-mono hover:underline"
								@click.stop
							>{{ r.instance }}</router-link>
						</td>
						<td class="px-3 py-2 text-gray-600 truncate max-w-[12rem]">{{ r.user || "" }}</td>
						<td class="px-3 py-2">
							<div class="flex items-center gap-1.5">
								<Badge :theme="STATUS_THEMES[r.status] || 'gray'" size="sm">{{ r.status }}</Badge>
								<span v-if="r.failed_steps" class="text-xs text-red-700 bg-red-50 rounded px-1.5" :title="`${r.failed_steps} failed step(s)`">{{ r.failed_steps }} err</span>
								<span v-if="r.child_runs" class="text-xs text-indigo-700 bg-indigo-50 rounded px-1.5" :title="`${r.child_runs} run(s) started by its tools`">+{{ r.child_runs }}</span>
							</div>
						</td>
						<td class="px-3 py-2 text-right text-gray-700">{{ r.steps }}</td>
						<td class="px-3 py-2 text-right text-gray-700">{{ r.tool_calls }}</td>
						<td class="px-3 py-2 text-right text-gray-700 whitespace-nowrap" :title="`wall clock ${fmtMs(r.duration_ms)}`">
							{{ fmtMs(r.agent_latency_ms) }}
						</td>
						<td class="px-3 py-2 text-right text-gray-700" :title="r.child_runs ? `this run alone: ${fmtNum(r.total_tokens)}` : ''">{{ fmtNum(r.tree_total_tokens) }}</td>
						<td class="px-3 py-2 text-right text-gray-700" :title="r.child_runs ? `this run alone: ${fmtCost(r.estimated_cost)}` : ''">{{ fmtCost(r.tree_estimated_cost) }}</td>
						<td class="px-3 py-2 text-xs" :class="GOAL_TONES[r.goal_completion] || 'text-gray-400'">{{ r.goal_completion || "" }}</td>
					</tr>
				</tbody>
			</table>
		</div>

		<footer class="bg-white border-t px-6 py-2 flex items-center justify-between text-sm text-gray-600">
			<span>{{ rangeLabel }}</span>
			<div class="flex gap-2">
				<Button size="sm" :disabled="start === 0 || loading" @click="load(start - pageLength)">Previous</Button>
				<Button size="sm" :disabled="start + runs.length >= total || loading" @click="load(start + pageLength)">Next</Button>
			</div>
		</footer>
	</div>
</template>

<script setup>
import { Autocomplete, Badge, Button, ErrorMessage, FormControl, frappeRequest } from "frappe-ui"
import { computed, onMounted, reactive, ref } from "vue"
import { useRoute } from "vue-router"
import { dayjs } from "@/dayjs"
import { fmtCost, fmtMs, fmtNum } from "@/utils/runFormat"

const API = "/api/method/one_bpmn.api.insights_api."
const PAGE_SIZES = [25, 50, 100].map((n) => ({ label: String(n), value: n }))
const ORIGINS = [
	{ label: "Production", value: "production" },
	{ label: "Eval", value: "eval" },
	{ label: "All origins", value: "all" },
]
const ORDERS = [
	{ label: "Newest first", value: "newest" },
	{ label: "Oldest first", value: "oldest" },
	{ label: "Slowest first", value: "slowest" },
	{ label: "Most steps", value: "steps" },
	{ label: "Most expensive", value: "cost" },
	{ label: "Most tokens", value: "tokens" },
]
const STATUS_THEMES = { Success: "green", Error: "red", Running: "blue", Suspended: "orange" }
const GOAL_TONES = { Achieved: "text-green-700", "Not Achieved": "text-red-700" }

const route = useRoute()
const loading = ref(false)
const error = ref("")
const runs = ref([])
const total = ref(0)
const start = ref(0)
const pageLength = ref(25)
const order = ref("newest")
const summary = ref(null)
const options = ref({ agents: [], users: [], models: [], statuses: [] })

const filters = reactive({
	agent_configuration: route.query.agent || "",
	status: route.query.status || "",
	origin: route.query.origin || "production",
	user: route.query.user || "",
	model: "",
	instance: route.query.instance || "",
	from_date: "",
	to_date: "",
	errors_only: route.query.errors === "1",
	search: "",
})

function choices(label, values) {
	return [{ label, value: "" }, ...values.map((v) => ({ label: v, value: v }))]
}
const agentOptions = computed(() => options.value.agents.map((v) => ({ label: v, value: v })))

// Autocomplete carries {label, value} while the filter holds a plain name, and
// its default comparator throws on a null model, so compare defensively.
function compareOption(a, b) {
	return a?.value === b?.value
}
const agentOption = computed({
	get: () => (filters.agent_configuration ? { label: filters.agent_configuration, value: filters.agent_configuration } : null),
	set: (opt) => {
		filters.agent_configuration = opt?.value || ""
		load()
	},
})
const userOptions = computed(() => choices("All users", options.value.users))
const modelOptions = computed(() => choices("All models", options.value.models))
const statusOptions = computed(() => choices("Any status", options.value.statuses))

const tiles = computed(() => {
	const s = summary.value
	if (!s) return []
	return [
		{ label: "Runs", value: fmtNum(s.runs), sub: `${fmtNum(s.conversations)} instances` },
		{ label: "Steps per run", value: s.steps_per_run, sub: `${fmtNum(s.steps)} steps` },
		{ label: "Median run", value: fmtMs(s.median_latency_ms), sub: `p95 ${fmtMs(s.p95_latency_ms)}` },
		{ label: "Runs with errors", value: fmtNum(s.error_runs), sub: `${s.error_rate}% of runs`, tone: s.error_runs ? "text-red-700" : "text-gray-900" },
		{ label: "Cost", value: fmtCost(s.cost), sub: `${fmtCost(s.cost_per_run)} per run` },
		{ label: "Tokens", value: fmtNum(s.tokens), sub: `cache read ${s.cache_read_share}%` },
	]
})

const rangeLabel = computed(() => {
	if (!total.value) return "No runs"
	const to = Math.min(start.value + runs.value.length, total.value)
	return `${start.value + 1} to ${to} of ${total.value}`
})

function fmtDate(v) {
	return v ? dayjs(v).format("DD MMM HH:mm") : ""
}

function call(method, params) {
	return frappeRequest({ url: API + method, method: "POST", params: params || {} })
}

async function load(from = 0) {
	loading.value = true
	error.value = ""
	try {
		const r = await call("list_runs", {
			...filters,
			errors_only: filters.errors_only ? 1 : 0,
			order: order.value,
			start: Math.max(from, 0),
			page_length: pageLength.value,
		})
		runs.value = r.runs || []
		total.value = r.total || 0
		start.value = r.start || 0
		summary.value = r.summary || null
	} catch (e) {
		error.value = e.message || String(e)
	} finally {
		loading.value = false
	}
}

async function loadOptions() {
	try {
		options.value = await call("run_filter_options", { origin: filters.origin })
	} catch (e) {
		// Filters without options still leave the list usable.
	}
}

function reloadAll() {
	loadOptions()
	load()
}

onMounted(() => {
	loadOptions()
	load()
})
</script>
