<template>
	<div class="h-full flex flex-col bg-gray-50">
		<!-- Header -->
		<header class="bg-white border-b px-6 py-4">
			<router-link
				:to="`/processa/evals/suite/${encodeURIComponent(run.suite || '')}`"
				class="text-xs text-gray-500 hover:underline"
			>← Suite</router-link>
			<div class="flex items-center justify-between mt-1">
				<div class="flex items-center gap-3">
					<h1 class="text-xl font-semibold text-gray-900">{{ run.display_title || runName }}</h1>
					<span class="inline-block px-2 py-0.5 rounded-full text-xs" :class="runPill(run.status)">
						{{ run.status }}
					</span>
					<span
						v-if="run.backend"
						class="text-xs"
						:class="run.backend === 'replay'
							? 'px-2 py-0.5 rounded-full bg-amber-50 text-amber-700'
							: 'text-gray-400'"
						:title="run.backend === 'replay'
							? 'Assertions were re-checked against each case\'s stored answer — the agent was not called'
							: 'The agent was called for every case in this run'"
					>{{ run.backend }}</span>
				</div>
				<div class="flex items-center gap-4">
					<label v-if="baselines.length" class="flex items-center gap-2 text-xs text-gray-500">
						Compare against
						<select
							v-model="baseline"
							class="border rounded px-2 py-1 text-xs text-gray-700 bg-white"
							:disabled="comparing"
							@change="fetchReview({ keepContent: true })"
						>
							<option value="">Most recent run of each case</option>
							<option v-for="b in baselines" :key="b.name" :value="b.name">
								{{ b.display_title }}
							</option>
						</select>
						<span v-if="comparing" class="text-gray-400">comparing…</span>
					</label>
					<router-link
						v-if="previous"
						:to="`/processa/evals/run/${encodeURIComponent(previous.name)}`"
						class="text-xs text-blue-600 hover:underline"
					>
						← {{ previous.display_title || previous.name }}
					</router-link>
				</div>
			</div>
		</header>

		<main class="flex-1 p-6 overflow-auto space-y-6">
			<!-- Summary cards -->
			<div class="grid grid-cols-2 lg:grid-cols-5 gap-4">
				<div class="bg-white rounded-lg shadow-sm p-4 border-l-4 border-green-500">
					<div class="text-xs text-gray-500 uppercase tracking-wide font-medium">Passed</div>
					<div class="text-2xl font-bold text-gray-900">{{ run.passed_cases ?? 0 }}</div>
				</div>
				<div class="bg-white rounded-lg shadow-sm p-4 border-l-4 border-red-500">
					<div class="text-xs text-gray-500 uppercase tracking-wide font-medium">Failed</div>
					<div class="text-2xl font-bold text-gray-900">{{ run.failed_cases ?? 0 }}</div>
				</div>
				<div class="bg-white rounded-lg shadow-sm p-4 border-l-4 border-blue-500">
					<div class="text-xs text-gray-500 uppercase tracking-wide font-medium">Total</div>
					<div class="text-2xl font-bold text-gray-900">{{ run.total_cases ?? 0 }}</div>
				</div>
				<div class="bg-white rounded-lg shadow-sm p-4 border-l-4 border-cyan-500">
					<div class="text-xs text-gray-500 uppercase tracking-wide font-medium">Tokens</div>
					<div class="text-2xl font-bold text-gray-900">{{ run.total_tokens ?? 0 }}</div>
				</div>
				<div class="bg-white rounded-lg shadow-sm p-4 border-l-4 border-purple-500">
					<div class="text-xs text-gray-500 uppercase tracking-wide font-medium">Cost</div>
					<div class="text-2xl font-bold text-gray-900">${{ (run.total_cost ?? 0).toFixed(4) }}</div>
				</div>
			</div>

			<!-- Comparison summary. Stated explicitly so that "nothing changed" is
			     a visible answer rather than an absence of one. -->
			<div
				v-if="baselines.length && !loading"
				class="bg-white rounded-lg shadow-sm px-6 py-3 flex items-center gap-4 text-sm"
			>
				<span class="text-xs uppercase tracking-wide text-gray-500 font-medium">
					vs {{ baseline ? baselineTitle : "most recent run of each case" }}
				</span>
				<span v-if="comparison.improved" class="text-green-600">▲ {{ comparison.improved }} improved</span>
				<span v-if="comparison.regressed" class="text-red-600">▼ {{ comparison.regressed }} regressed</span>
				<span v-if="comparison.unchanged" class="text-gray-500">{{ comparison.unchanged }} unchanged</span>
				<span v-if="comparison.missing" class="text-gray-400">
					{{ comparison.missing }} with no baseline
				</span>
				<span
					v-if="!comparison.improved && !comparison.regressed && comparison.unchanged"
					class="text-gray-400 text-xs"
				>· no change in any case</span>
			</div>

			<div v-if="loading" class="bg-white rounded-lg shadow-sm p-6 space-y-3 animate-pulse">
				<div v-for="n in 3" :key="n" class="h-16 bg-gray-100 rounded"></div>
			</div>

			<!-- Per-case results -->
			<div v-for="res in results" :key="res.eval_case" class="bg-white rounded-lg shadow-sm">
				<div class="border-b px-6 py-3 flex items-center justify-between">
					<div class="flex items-center gap-3">
						<span class="font-medium text-gray-900">{{ res.case_title }}</span>
						<span class="inline-block px-2 py-0.5 rounded-full text-xs" :class="runPill(res.status)">
							{{ res.status }}
						</span>
						<span
							v-if="delta(res)"
							class="text-xs"
							:class="delta(res).cls"
							:title="delta(res).title"
						>{{ delta(res).label }}</span>
					</div>
					<span class="text-xs text-gray-400">{{ res.tokens_used }} tok · ${{ (res.cost || 0).toFixed(4) }}</span>
				</div>
				<div class="px-6 py-4 space-y-4">
					<!-- What was actually under test. On the map path this is the
					     document, NOT the case's prompt: the map's own shape prompt is
					     what reaches the model, rendered against this record. Showing
					     the prompt alone let a case name one record while the agent was
					     asked about another. -->
					<div v-if="res.runs_map && res.subject_docname">
						<div class="text-xs uppercase tracking-wide text-gray-500 font-medium mb-2">
							Document under test
						</div>
						<div class="flex items-center gap-2 flex-wrap">
							<code class="text-xs bg-gray-50 rounded px-2 py-1">
								{{ res.subject_doctype }} / {{ res.subject_docname }}
							</code>
							<span
								v-if="res.subject_source === 'source_run'"
								class="text-xs text-gray-400"
								title="Inherited from the run this case was captured from, because the case does not name a document itself"
							>from source run</span>
						</div>
					</div>

					<!-- Prompt under test -->
					<div v-if="res.input_user_prompt">
						<div class="text-xs uppercase tracking-wide text-gray-500 font-medium mb-2">
							Prompt
							<span v-if="res.runs_map" class="normal-case tracking-normal text-gray-400 font-normal">
								— not sent; the map's own prompt is used
							</span>
						</div>
						<div
							v-if="promptDocMismatch(res)"
							class="mb-2 flex items-start gap-2 rounded border border-amber-200 bg-amber-50 px-3 py-2"
						>
							<Icon icon="lucide:alert-triangle" class="w-4 h-4 text-amber-600 shrink-0 mt-0.5" />
							<p class="text-xs text-amber-800">
								This prompt names <code>{{ promptDocMismatch(res).inPrompt }}</code>, but the case
								ran against <code>{{ promptDocMismatch(res).ranAgainst }}</code>. On the map path
								the prompt is ignored — edit the case's <code>input_context.context_docname</code>
								to change which record is tested.
							</p>
						</div>
						<pre class="text-xs bg-gray-50 rounded p-3 whitespace-pre-wrap overflow-auto max-h-40">{{ res.input_user_prompt }}</pre>
						<details v-if="res.expected_output" class="mt-2">
							<summary class="text-xs text-gray-500 cursor-pointer">Expected output</summary>
							<pre class="text-xs bg-gray-50 rounded p-3 mt-2 whitespace-pre-wrap overflow-auto">{{ res.expected_output }}</pre>
						</details>
					</div>

					<!-- Assertions -->
					<div>
						<div class="text-xs uppercase tracking-wide text-gray-500 font-medium mb-2">Assertions</div>
						<div
							v-for="(a, i) in res.assertions"
							:key="i"
							class="border border-gray-100 rounded-md p-3 mb-2"
						>
							<div class="flex items-center gap-2">
								<Icon
									:icon="a.passed ? 'lucide:check-circle' : 'lucide:x-circle'"
									class="w-4 h-4"
									:class="a.passed ? 'text-green-600' : 'text-red-600'"
								/>
								<span class="text-sm font-medium text-gray-800">{{ a.assertion_type }}</span>
								<span v-if="a.score !== undefined" class="text-xs text-gray-500">score {{ a.score }}</span>
							</div>
							<div v-if="a.value" class="mt-1 flex items-baseline gap-2">
								<span class="text-xs text-gray-500 shrink-0">{{ assertionValueLabel(a.assertion_type) }}:</span>
								<pre class="text-xs text-gray-700 bg-gray-50 rounded px-2 py-1 m-0 whitespace-pre-wrap break-words max-h-24 overflow-auto grow">{{ a.value }}</pre>
							</div>
							<p v-if="a.explanation" class="text-sm text-gray-600 mt-1">Judge: {{ a.explanation }}</p>
							<p v-else-if="a.message" class="text-sm text-gray-500 mt-1">{{ a.message }}</p>
						</div>
						<p v-if="!res.assertions.length" class="text-sm text-gray-400">No assertions.</p>
					</div>

					<!-- What the agent did: steps, and the tools each one called.
					     Answering "which tools ran?" used to mean leaving this screen
					     and opening each AI Agent Step record by hand. -->
					<div v-if="res.agent_runs && res.agent_runs.length">
						<div class="text-xs uppercase tracking-wide text-gray-500 font-medium mb-2">
							Agent activity
						</div>
						<div
							v-for="ar in res.agent_runs"
							:key="ar.name"
							class="border border-gray-100 rounded-md mb-2"
						>
							<div class="px-3 py-2 flex items-center gap-3 flex-wrap border-b border-gray-100">
								<span class="text-sm font-medium text-gray-800">
									{{ ar.bpmn_label || ar.bpmn_id || ar.name }}
								</span>
								<span class="inline-block px-2 py-0.5 rounded-full text-xs" :class="runPill(ar.status)">
									{{ ar.status }}
								</span>
								<span
									class="text-xs px-2 py-0.5 rounded-full"
									:class="ar.tool_call_count
										? 'bg-indigo-50 text-indigo-700'
										: 'bg-gray-100 text-gray-500'"
								>
									{{ ar.tool_call_count }} tool call{{ ar.tool_call_count === 1 ? "" : "s" }}
								</span>
								<span v-if="ar.model" class="text-xs text-gray-400">{{ ar.model }}</span>
								<span class="text-xs text-gray-400 ml-auto">
									{{ ar.total_tokens || 0 }} tok · ${{ (ar.estimated_cost || 0).toFixed(4) }}
								</span>
								<a
									:href="`/app/ai-agent-run/${encodeURIComponent(ar.name)}`"
									target="_blank"
									rel="noopener"
									class="text-xs text-blue-600 hover:underline"
								>full run ↗</a>
							</div>

							<p v-if="ar.error_message" class="px-3 py-2 text-sm text-red-600">
								{{ ar.error_message }}
							</p>

							<!-- Tool calls first: they are what this section is for. The
							     whole step transcript sits behind a disclosure so a long
							     conversation does not bury them. -->
							<div v-if="ar.tool_call_count" class="px-3 py-2 space-y-2">
								<div
									v-for="(tc, i) in toolCalls(ar)"
									:key="i"
									class="border border-gray-100 rounded p-2"
								>
									<div class="flex items-center gap-2 flex-wrap">
										<Icon icon="lucide:wrench" class="w-3.5 h-3.5 text-indigo-600" />
										<code class="text-xs font-medium text-gray-800">{{ tc.tool_name }}</code>
										<span class="text-xs text-gray-400">step #{{ tc.step_index }}</span>
										<span v-if="tc.tool_source" class="text-xs text-gray-400">
											{{ tc.tool_source }}
										</span>
										<span
											v-if="toolFailed(tc)"
											class="text-xs px-1.5 py-0.5 rounded bg-red-50 text-red-700"
											title="The shape ran, but returned an error payload to the model"
										>returned an error</span>
									</div>
									<div v-if="tc.tool_args" class="mt-1 flex items-baseline gap-2">
										<span class="text-xs text-gray-500 shrink-0">Arguments:</span>
										<pre class="text-xs text-gray-700 bg-gray-50 rounded px-2 py-1 m-0 whitespace-pre-wrap break-words max-h-24 overflow-auto grow">{{ pretty(tc.tool_args) }}</pre>
									</div>
									<div v-if="tc.tool_result" class="mt-1 flex items-baseline gap-2">
										<span class="text-xs text-gray-500 shrink-0">Result:</span>
										<pre class="text-xs text-gray-700 bg-gray-50 rounded px-2 py-1 m-0 whitespace-pre-wrap break-words max-h-40 overflow-auto grow">{{ pretty(tc.tool_result) }}</pre>
									</div>
								</div>
							</div>
							<p v-else class="px-3 py-2 text-sm text-gray-400">
								The agent called no tools in this run.
							</p>

							<details v-if="ar.steps && ar.steps.length" class="px-3 pb-2">
								<summary class="text-xs text-gray-500 cursor-pointer">
									Full transcript ({{ ar.steps.length }} steps)
								</summary>
								<div
									v-for="s in ar.steps"
									:key="s.step_index"
									class="mt-2 border-l-2 border-gray-100 pl-3"
								>
									<div class="text-xs text-gray-500">
										#{{ s.step_index }} · {{ s.role }}
										<span v-if="s.tool_calls.length" class="text-indigo-600">
											· {{ s.tool_calls.length }} tool call{{ s.tool_calls.length === 1 ? "" : "s" }}
										</span>
									</div>
									<pre
										v-if="s.content"
										class="text-xs bg-gray-50 rounded p-2 mt-1 whitespace-pre-wrap overflow-auto max-h-40"
									>{{ s.content }}</pre>
								</div>
							</details>
						</div>
					</div>

					<!-- Actual output -->
					<div v-if="res.error_message" class="text-sm text-red-600">{{ res.error_message }}</div>
					<details v-if="res.actual_output">
						<summary class="text-xs text-gray-500 cursor-pointer">Actual output</summary>
						<pre class="text-xs bg-gray-50 rounded p-3 mt-2 whitespace-pre-wrap overflow-auto">{{ res.actual_output }}</pre>
					</details>
				</div>
			</div>

			<div v-if="!loading && !results.length" class="bg-white rounded-lg shadow-sm p-8 text-center text-sm text-gray-500">
				No results recorded for this run.
			</div>
		</main>
	</div>
</template>

<script setup>
import { ref, computed, onMounted } from "vue"
import { useRoute } from "vue-router"
import { frappeRequest } from "frappe-ui"
import { Icon } from "@iconify/vue"

const route = useRoute()
const runName = route.params.run

const loading = ref(true)
// Changing the baseline re-fetches, but blanking the page to a skeleton for it
// made a correct "nothing changed" answer look like a failed reload.
const comparing = ref(false)
const run = ref({})
const results = ref([])
const previous = ref(null)
const baselines = ref([])
const caseBaselines = ref({})
// "" = auto: compare each case against the most recent earlier run that covered
// it. A run name pins every case to that one run instead.
const baseline = ref("")

// What an assertion's `value` means depends on its type, so it is labelled
// rather than shown bare. "Substring not found." on its own forced the reader
// to open the case to learn WHICH substring — the value is already in the
// result payload, it just was not rendered.
const ASSERTION_VALUE_LABELS = {
	contains: "Expected substring",
	regex: "Pattern",
	equals: "Expected output",
	schema_valid: "Schema",
	llm_judge: "Rubric",
}

function assertionValueLabel(type) {
	return ASSERTION_VALUE_LABELS[type] || "Expected"
}

// Editing a captured case's PROMPT is the intuitive way to point it at another
// record, and on the map path it does nothing at all — the prompt is not sent, and
// the document comes from input_context. Catch the mismatch and say so, rather
// than leaving the reader to notice that two record ids differ.
const DOCNAME_PATTERN = /\b[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)*-\d{3,}\b/g

function promptDocMismatch(res) {
	if (!res.runs_map || !res.subject_docname || !res.input_user_prompt) return null
	const mentioned = res.input_user_prompt.match(DOCNAME_PATTERN) || []
	if (!mentioned.length) return null
	if (mentioned.includes(res.subject_docname)) return null
	return { inPrompt: mentioned[0], ranAgainst: res.subject_docname }
}

// Every tool call across a run's steps, flattened and tagged with the step it
// belongs to. Tool calls are the answer people come to this screen for, so they
// are listed together rather than hidden one level down inside each step.
function toolCalls(agentRun) {
	const out = []
	for (const step of agentRun.steps || []) {
		for (const tc of step.tool_calls || []) {
			out.push({ ...tc, step_index: step.step_index })
		}
	}
	return out
}

// A shape tool never raises — execute_shape returns {"error": ...} to the model
// instead — so `status` stays "Success" even when the lookup failed. The result
// payload is the only place that shows it, so flag it explicitly.
function toolFailed(tc) {
	if (tc.status === "Error") return true
	const raw = tc.tool_result
	if (!raw) return false
	try {
		const parsed = typeof raw === "string" ? JSON.parse(raw) : raw
		return Boolean(parsed && typeof parsed === "object" && parsed.error)
	} catch {
		return false
	}
}

// JSON payloads read far better indented; anything that is not JSON is shown
// exactly as stored.
function pretty(raw) {
	if (raw === null || raw === undefined) return ""
	if (typeof raw === "object") return JSON.stringify(raw, null, 2)
	try {
		return JSON.stringify(JSON.parse(raw), null, 2)
	} catch {
		return String(raw)
	}
}

function runPill(status) {
	if (status === "Passed") return "bg-green-50 text-green-700"
	if (status === "Failed" || status === "Error") return "bg-red-50 text-red-700"
	if (status === "Running") return "bg-yellow-50 text-yellow-700"
	return "bg-gray-100 text-gray-500"
}

// An absent badge used to be ambiguous — "nothing changed" and "no earlier run
// to compare against" looked identical. Every case now reports one or the other.
function delta(res) {
	const base = caseBaselines.value?.[res.eval_case]
	if (!base) {
		return {
			label: baseline.value ? "not in baseline run" : "no earlier run",
			cls: "text-gray-400",
			title: baseline.value
				? "The selected baseline run did not cover this case."
				: "This case has not run before, so there is nothing to compare against.",
		}
	}
	const from = base.run_title || base.run
	if (base.status === res.status) {
		return { label: `unchanged vs ${from}`, cls: "text-gray-400", title: `Also ${base.status} in ${from}.` }
	}
	if (res.status === "Passed" && base.status === "Failed") {
		return { label: `▲ improved vs ${from}`, cls: "text-green-600", title: `Was ${base.status} in ${from}.` }
	}
	if (res.status === "Failed" && base.status === "Passed") {
		return { label: `▼ regressed vs ${from}`, cls: "text-red-600", title: `Was ${base.status} in ${from}.` }
	}
	return { label: `was ${base.status} in ${from}`, cls: "text-gray-400", title: "" }
}

// Summary of the comparison, so choosing a baseline always changes something
// visible. Without it the only feedback was muted text beside each case, which
// on a suite whose results never varied looked like the picker doing nothing.
const baselineTitle = computed(
	() => baselines.value.find((b) => b.name === baseline.value)?.display_title || baseline.value
)

const comparison = computed(() => {
	let improved = 0, regressed = 0, unchanged = 0, missing = 0
	for (const res of results.value) {
		const base = caseBaselines.value?.[res.eval_case]
		if (!base) missing += 1
		else if (base.status === res.status) unchanged += 1
		else if (res.status === "Passed") improved += 1
		else if (res.status === "Failed") regressed += 1
		else unchanged += 1
	}
	return { improved, regressed, unchanged, missing, total: results.value.length }
})

async function fetchReview({ keepContent = false } = {}) {
	if (keepContent) comparing.value = true
	else loading.value = true
	try {
		const params = { run: runName }
		if (baseline.value) params.baseline = baseline.value
		const res = await frappeRequest({
			url: "/api/method/one_bpmn.api.eval_api.get_run_review",
			method: "GET",
			params,
		})
		run.value = res?.run || {}
		results.value = res?.results || []
		previous.value = res?.previous || null
		baselines.value = res?.baselines || []
		caseBaselines.value = res?.case_baselines || {}
	} catch (e) {
		console.error("Failed to load run review:", e)
	} finally {
		loading.value = false
		comparing.value = false
	}
}

onMounted(() => fetchReview())
</script>
