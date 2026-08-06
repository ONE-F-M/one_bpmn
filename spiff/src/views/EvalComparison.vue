<template>
	<div class="h-full flex flex-col bg-gray-50">
		<!-- Header -->
		<header class="bg-white border-b px-6 py-4">
			<router-link
				:to="`/processa/evals/suite/${encodeURIComponent(data.suite || '')}`"
				class="text-xs text-gray-500 hover:underline"
			>← Suite</router-link>
			<div class="flex items-center justify-between mt-1">
				<h1 class="text-xl font-semibold text-gray-900">
					A/B comparison<span v-if="data.suite_title"> · {{ data.suite_title }}</span>
				</h1>
				<label v-if="candidates.length" class="flex items-center gap-2 text-xs text-gray-500">
					Compare against
					<select
						:value="runB"
						class="border rounded px-2 py-1 text-xs text-gray-700 bg-white"
						:disabled="loading"
						@change="pickB($event.target.value)"
					>
						<option v-for="c in candidates" :key="c.name" :value="c.name">
							{{ c.display_title }}{{ c.same_agent ? " (same agent)" : "" }}
						</option>
					</select>
				</label>
			</div>
		</header>

		<main class="flex-1 p-6 overflow-auto space-y-6">
			<div v-if="loading" class="text-sm text-gray-500">Loading comparison…</div>
			<div v-else-if="error" class="bg-white rounded-lg shadow-sm p-6 border-l-4 border-red-500">
				<div class="font-medium text-gray-900">This comparison can't be shown</div>
				<p class="text-sm text-gray-600 mt-1 whitespace-pre-line">{{ error }}</p>
			</div>

			<template v-else-if="data.a">
				<!-- Comparability notes. Deliberately ABOVE the numbers: a caveat
				     printed underneath a headline gets read second, if at all. -->
				<div v-if="data.notes && data.notes.length" class="space-y-2">
					<div
						v-for="(n, i) in data.notes"
						:key="i"
						class="rounded-lg p-3 text-sm border-l-4"
						:class="noteClass(n.level)"
					>
						<span class="font-medium">{{ noteLabel(n.level) }}</span> {{ n.message }}
					</div>
				</div>

				<div
					v-if="data.blocked"
					class="bg-white rounded-lg shadow-sm p-6 text-sm text-gray-600"
				>
					The per-agent figures are hidden because the two runs can't be compared —
					see the reason above. Fix that and the comparison will appear here.
				</div>

				<template v-else>
					<!-- Verdict -->
					<div class="bg-white rounded-lg shadow-sm p-5">
						<div class="text-xs text-gray-500 uppercase tracking-wide font-medium">
							Across {{ data.a.cases_compared }} shared case{{ data.a.cases_compared === 1 ? "" : "s" }}
						</div>
						<div class="mt-2 text-lg text-gray-900">{{ verdict }}</div>
						<div class="mt-3 flex gap-6 text-sm text-gray-600">
							<span>{{ shortName(data.a) }} won <strong>{{ data.tally.a_wins }}</strong></span>
							<span>{{ shortName(data.b) }} won <strong>{{ data.tally.b_wins }}</strong></span>
							<span>Tied <strong>{{ data.tally.ties }}</strong></span>
						</div>
					</div>

					<!-- Side by side -->
					<div class="grid grid-cols-1 lg:grid-cols-2 gap-4">
						<div
							v-for="side in [data.a, data.b]"
							:key="side.run"
							class="bg-white rounded-lg shadow-sm p-5"
						>
							<div class="flex items-center justify-between">
								<div>
									<div class="font-medium text-gray-900">{{ shortName(side) }}</div>
									<router-link
										:to="`/processa/evals/run/${encodeURIComponent(side.run)}`"
										class="text-xs text-blue-600 hover:underline"
									>open this run →</router-link>
								</div>
								<span class="text-xs px-2 py-0.5 rounded-full" :class="runPill(side.status)">
									{{ side.status }}
								</span>
							</div>

							<div class="mt-4 grid grid-cols-3 gap-3">
								<Metric label="Pass rate" :value="pct(side.pass_rate)" :highlight="best('pass_rate', side, 'high')" />
								<Metric label="Mean latency" :value="ms(side.mean_latency_ms)" :highlight="best('mean_latency_ms', side, 'low')" />
								<Metric label="Suite cost" :value="money(side.total_cost)" :highlight="best('total_cost', side, 'low')" />
							</div>

							<div class="mt-2 text-xs text-gray-500">
								{{ side.passed }} passed · {{ side.failed }} failed
								<template v-if="side.errored">· {{ side.errored }} errored</template>
								<template v-if="side.latency_samples === 0"> · latency not measured</template>
							</div>

							<!-- Cost split. The cache columns are the point: an agent can
							     look cheap only because it is reading a warm cache. -->
							<div class="mt-4 border-t pt-3">
								<div class="text-xs text-gray-500 uppercase tracking-wide font-medium mb-2">
									Agent cost split
								</div>
								<dl class="grid grid-cols-2 gap-x-4 gap-y-1 text-xs">
									<div class="flex justify-between"><dt class="text-gray-500">Input</dt><dd>{{ money(side.cost_split.input) }}</dd></div>
									<div class="flex justify-between"><dt class="text-gray-500">Output</dt><dd>{{ money(side.cost_split.output) }}</dd></div>
									<div class="flex justify-between"><dt class="text-gray-500">Cache read</dt><dd>{{ money(side.cost_split.cache_read) }}</dd></div>
									<div class="flex justify-between"><dt class="text-gray-500">Cache write</dt><dd>{{ money(side.cost_split.cache_write) }}</dd></div>
								</dl>
								<div class="mt-2 text-xs text-gray-400">
									{{ (side.cache_tokens.read || 0).toLocaleString() }} cache-read /
									{{ (side.cache_tokens.write || 0).toLocaleString() }} cache-write tokens
								</div>
							</div>
						</div>
					</div>

					<!-- Per case -->
					<div class="bg-white rounded-lg shadow-sm overflow-hidden">
						<table class="w-full text-sm">
							<thead class="bg-gray-50 text-xs text-gray-500 uppercase tracking-wide">
								<tr>
									<th class="text-left px-4 py-2 font-medium">Case</th>
									<th class="text-left px-4 py-2 font-medium">{{ shortName(data.a) }}</th>
									<th class="text-left px-4 py-2 font-medium">{{ shortName(data.b) }}</th>
									<th class="text-left px-4 py-2 font-medium">Outcome</th>
								</tr>
							</thead>
							<tbody>
								<tr v-for="c in data.cases" :key="c.eval_case" class="border-t">
									<td class="px-4 py-2 text-gray-900">{{ c.case_title }}</td>
									<td class="px-4 py-2"><StatusPill :status="c.status_a" /></td>
									<td class="px-4 py-2"><StatusPill :status="c.status_b" /></td>
									<td class="px-4 py-2">
										<span class="text-xs px-2 py-0.5 rounded-full" :class="outcomeClass(c.outcome)">
											{{ outcomeLabel(c.outcome) }}
										</span>
									</td>
								</tr>
							</tbody>
						</table>
					</div>
				</template>
			</template>
		</main>
	</div>
</template>

<script setup>
// WI-001821: two runs of one suite, side by side, so an agent can be chosen on
// evidence instead of on impression. Reads only — the runs themselves were
// produced by run_eval_comparison (or by two ordinary runs the user pairs here).
import { computed, h, onMounted, ref, watch } from "vue"
import { useRouter } from "vue-router"
import { frappeRequest } from "frappe-ui"

const props = defineProps({ runA: String, runB: String })
const router = useRouter()

const data = ref({})
const candidates = ref([])
const loading = ref(true)
const error = ref("")
const runB = ref(props.runB || "")

const Metric = (p) =>
	h("div", [
		h("div", { class: "text-xs text-gray-500" }, p.label),
		h(
			"div",
			{ class: ["text-lg font-semibold", p.highlight ? "text-green-700" : "text-gray-900"] },
			p.value
		),
	])
Metric.props = ["label", "value", "highlight"]

const StatusPill = (p) =>
	h("span", { class: ["text-xs px-2 py-0.5 rounded-full", runPill(p.status)] }, p.status || "—")
StatusPill.props = ["status"]

function runPill(status) {
	if (status === "Passed") return "bg-green-50 text-green-700"
	if (status === "Failed") return "bg-red-50 text-red-700"
	if (status === "Error") return "bg-amber-50 text-amber-700"
	return "bg-gray-100 text-gray-600"
}

function noteClass(level) {
	if (level === "blocking") return "bg-red-50 border-red-500 text-red-900"
	if (level === "warning") return "bg-amber-50 border-amber-500 text-amber-900"
	return "bg-blue-50 border-blue-400 text-blue-900"
}
function noteLabel(level) {
	if (level === "blocking") return "Can't compare:"
	if (level === "warning") return "Not like for like:"
	return "Bear in mind:"
}

function shortName(side) {
	return side.agent_name || side.agent || "unknown agent"
}

const pct = (v) => (v === null || v === undefined ? "—" : `${v}%`)
const ms = (v) => (v === null || v === undefined ? "—" : `${Number(v).toLocaleString()} ms`)
const money = (v) => (v === null || v === undefined ? "—" : `$${Number(v).toFixed(4)}`)

// Highlight the better side, but only when the two actually differ — colouring
// a dead heat green on one side invents a winner.
function best(field, side, direction) {
	const a = data.value.a?.[field]
	const b = data.value.b?.[field]
	if (a === null || b === null || a === undefined || b === undefined || a === b) return false
	const winner = direction === "high" ? (a > b ? "a" : "b") : a < b ? "a" : "b"
	return side.run === data.value[winner]?.run
}

const verdict = computed(() => {
	const t = data.value.tally
	if (!t) return ""
	const a = shortName(data.value.a)
	const b = shortName(data.value.b)
	if (t.a_wins === t.b_wins) {
		return `No separation between ${a} and ${b} on case outcomes — compare latency and cost below.`
	}
	const [lead, trail, n] =
		t.a_wins > t.b_wins ? [a, b, t.a_wins - t.b_wins] : [b, a, t.b_wins - t.a_wins]
	return `${lead} passed ${n} case${n === 1 ? "" : "s"} more than ${trail}.`
})

function outcomeLabel(o) {
	if (o === "tie") return "Tie"
	return `${shortName(o === "a" ? data.value.a : data.value.b)} wins`
}
function outcomeClass(o) {
	return o === "tie" ? "bg-gray-100 text-gray-600" : "bg-green-50 text-green-700"
}

async function fetchComparison() {
	loading.value = true
	error.value = ""
	try {
		data.value = await frappeRequest({
			url: "/api/method/one_bpmn.api.eval_api.get_run_comparison",
			method: "POST",
			params: { run_a: props.runA, run_b: runB.value || undefined },
		})
		runB.value = data.value?.b?.run || runB.value
	} catch (e) {
		error.value = e?.messages?.join("\n") || e?.message || String(e)
		data.value = {}
	} finally {
		loading.value = false
	}
}

async function fetchCandidates() {
	try {
		candidates.value = await frappeRequest({
			url: "/api/method/one_bpmn.api.eval_api.list_comparable_runs",
			method: "POST",
			params: { run: props.runA },
		})
	} catch (e) {
		candidates.value = []
	}
}

function pickB(name) {
	// Keep the URL honest, so the comparison is a shareable link.
	router.replace(
		`/processa/evals/compare/${encodeURIComponent(props.runA)}/${encodeURIComponent(name)}`
	)
}

watch(() => props.runB, (v) => { runB.value = v || ""; fetchComparison() })

onMounted(() => {
	fetchComparison()
	fetchCandidates()
})
</script>
