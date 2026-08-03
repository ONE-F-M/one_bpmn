<template>
	<div class="h-full flex flex-col bg-gray-50">
		<!-- Header -->
		<header class="bg-white border-b px-6 py-4">
			<router-link to="/processa/evals" class="text-xs text-gray-500 hover:underline">← Evals</router-link>
			<div class="flex items-center justify-between mt-1">
				<div>
					<div class="flex items-center gap-2">
						<h1 class="text-xl font-semibold text-gray-900">{{ suite.title || suiteName }}</h1>
						<span
							v-if="suite.eval_type"
							class="text-xs px-2 py-0.5 rounded-full"
							:class="suite.eval_type === 'Agent' ? 'bg-indigo-50 text-indigo-700' : 'bg-blue-50 text-blue-700'"
						>
							{{ suite.eval_type }} eval
						</span>
					</div>
					<div class="text-xs text-gray-400">
						{{ suite.agent_name || suite.agent_configuration || "no agent" }} ·
						{{ suite.process_model || "no process" }}
					</div>
				</div>
				<div class="flex items-center gap-2">
					<Button icon-left="file-plus" @click="openNewCase">New case</Button>
					<Button icon-left="git-branch" @click="showFromRun = true">From run</Button>
					<Button variant="subtle" icon-left="play" :disabled="!selected.length" :loading="runningSelected" @click="runSelected">
						Run selected ({{ selected.length }})
					</Button>
					<Button
						variant="subtle"
						icon-left="refresh-cw"
						:disabled="!canRecheck"
						:loading="rechecking"
						:title="canRecheck ? 'Re-evaluate assertions against the last stored answers — no new agent calls' : 'Run the suite once before re-checking'"
						@click="recheckSuite"
					>Re-check</Button>
					<Button variant="solid" icon-left="play" :loading="runningSuite" @click="runWholeSuite">Run suite</Button>
				</div>
			</div>
		</header>

		<main class="flex-1 p-6 overflow-auto space-y-6">
			<div v-if="loadError" class="bg-red-50 text-red-700 text-sm rounded-lg px-4 py-3">{{ loadError }}</div>

			<!-- Dashboard -->
			<div class="grid grid-cols-2 md:grid-cols-4 xl:grid-cols-7 gap-4">
				<div class="bg-white rounded-lg shadow-sm p-4 border-l-4 border-blue-500">
					<div class="text-xs text-gray-500 uppercase tracking-wide font-medium">Cases</div>
					<div class="text-2xl font-bold text-gray-900">{{ metrics.cases ?? 0 }}</div>
				</div>
				<div class="bg-white rounded-lg shadow-sm p-4 border-l-4 border-indigo-500">
					<div class="text-xs text-gray-500 uppercase tracking-wide font-medium">Runs</div>
					<div class="text-2xl font-bold text-gray-900">{{ metrics.runs ?? 0 }}</div>
				</div>
				<div class="bg-white rounded-lg shadow-sm p-4 border-l-4" :class="metrics.latest?.status === 'Passed' ? 'border-green-500' : metrics.latest ? 'border-red-500' : 'border-gray-300'">
					<div class="text-xs text-gray-500 uppercase tracking-wide font-medium">Latest run</div>
					<div class="text-base font-bold text-gray-900">
						{{ metrics.latest ? `${metrics.latest.status} · ${metrics.latest.passed}/${metrics.latest.total}` : "—" }}
					</div>
				</div>
				<div class="bg-white rounded-lg shadow-sm p-4 border-l-4 border-green-500">
					<div class="text-xs text-gray-500 uppercase tracking-wide font-medium">Pass rate</div>
					<div class="text-2xl font-bold text-gray-900">{{ metrics.pass_rate != null ? metrics.pass_rate + "%" : "—" }}</div>
					<svg v-if="sparkPoints" viewBox="0 0 100 20" preserveAspectRatio="none" class="w-full h-5 mt-1">
						<polyline :points="sparkPoints" fill="none" stroke="currentColor" stroke-width="2" class="text-green-500" />
					</svg>
				</div>
				<div class="bg-white rounded-lg shadow-sm p-4 border-l-4 border-amber-500">
					<div class="text-xs text-gray-500 uppercase tracking-wide font-medium">Tokens (latest)</div>
					<div class="text-2xl font-bold text-gray-900">{{ fmt(metrics.latest_tokens ?? 0) }}</div>
				</div>
				<div class="bg-white rounded-lg shadow-sm p-4 border-l-4 border-purple-500">
					<div class="text-xs text-gray-500 uppercase tracking-wide font-medium">Cost (latest)</div>
					<div class="text-2xl font-bold text-gray-900">{{ fmtCost(metrics.latest_cost ?? 0) }}</div>
				</div>
				<div class="bg-white rounded-lg shadow-sm p-4 border-l-4 border-cyan-500">
					<div class="text-xs text-gray-500 uppercase tracking-wide font-medium">Assertion coverage</div>
					<div class="text-2xl font-bold text-gray-900">{{ metrics.assertion_coverage?.with_assertions ?? 0 }} / {{ metrics.assertion_coverage?.total ?? 0 }}</div>
				</div>
			</div>

			<!-- Cases -->
			<div class="bg-white rounded-lg shadow-sm">
				<div class="border-b px-6 py-3 text-sm font-semibold text-gray-700">
					Cases <span class="text-gray-400 font-normal">({{ cases.length }})</span>
				</div>
				<div v-if="loading" class="p-6 space-y-3 animate-pulse">
					<div v-for="n in 3" :key="n" class="h-8 bg-gray-100 rounded"></div>
				</div>
				<div v-else-if="!cases.length" class="p-8 text-center text-sm text-gray-500">
					No cases yet — add one with "New case" or "From run".
				</div>
				<table v-else class="w-full text-sm">
					<thead>
						<tr class="text-left text-xs uppercase tracking-wide text-gray-500 border-b">
							<th class="px-4 py-3 w-8"><input type="checkbox" :checked="allSelected" @change="toggleAll" /></th>
							<th class="px-4 py-3 font-medium">Case</th>
							<th class="px-4 py-3 font-medium">Assertions</th>
							<th class="px-4 py-3 font-medium text-right">Actions</th>
						</tr>
					</thead>
					<tbody>
						<tr v-for="c in cases" :key="c.name" class="border-b border-gray-100 hover:bg-gray-50">
							<td class="px-4 py-3"><input type="checkbox" :value="c.name" v-model="selected" /></td>
							<td class="px-4 py-3">
								<div class="font-medium text-gray-900">{{ c.title }}</div>
								<div v-if="c.source_run" class="text-xs text-gray-400">from run</div>
							</td>
							<td class="px-4 py-3">
								<span v-for="t in c.assertion_types" :key="t" class="inline-block px-2 py-0.5 rounded-full text-xs bg-gray-100 text-gray-600 mr-1">{{ t }}</span>
								<span v-if="!c.assertion_types.length" class="text-xs text-amber-600">no assertions</span>
							</td>
							<td class="px-4 py-3 text-right whitespace-nowrap">
								<Button variant="ghost" icon-left="pencil" @click="openEditCase(c)">Edit</Button>
								<Button
									variant="ghost"
									icon-left="refresh-cw"
									:disabled="!canRecheck"
									:loading="recheckingCase[c.name]"
									:title="canRecheck ? 'Re-evaluate this case\'s assertions against its last stored answer' : 'Run this case once before re-checking'"
									@click="recheckCase(c)"
								>Re-check</Button>
								<Button icon-left="play" :loading="runningCase[c.name]" @click="runCase(c)">Run</Button>
							</td>
						</tr>
					</tbody>
				</table>
			</div>

			<!-- Runs -->
			<div class="bg-white rounded-lg shadow-sm">
				<div class="border-b px-6 py-3 text-sm font-semibold text-gray-700">Recent runs</div>
				<div v-if="!runs.length" class="p-8 text-center text-sm text-gray-500">No runs yet.</div>
				<table v-else class="w-full text-sm">
					<tbody>
						<tr v-for="r in runs" :key="r.name" class="border-b border-gray-100 hover:bg-gray-50">
							<td class="px-6 py-3">
								<router-link :to="`/processa/evals/run/${encodeURIComponent(r.name)}`" class="text-gray-900 hover:underline">
									{{ r.display_title || r.name }}
								</router-link>
							</td>
							<td class="px-6 py-3 text-gray-600" :title="(r.case_names || []).join(', ')">
								{{ r.case_label }}
							</td>
							<td class="px-6 py-3">
								<span class="inline-block px-2 py-0.5 rounded-full text-xs" :class="runPill(r.status)">{{ r.status }}</span>
							</td>
							<td class="px-6 py-3 text-gray-600">{{ r.passed_cases }}/{{ r.total_cases }} passed</td>
							<td class="px-6 py-3 text-gray-400 text-xs">{{ r.started_at }}</td>
						</tr>
					</tbody>
				</table>
			</div>
		</main>

		<!-- Case editor modal (new + edit) -->
		<Dialog v-model="showCaseEditor" :options="{ title: caseMode === 'edit' ? 'Edit case' : 'New eval case', size: '3xl' }">
			<template #body-content>
				<div class="space-y-3">
					<div class="text-xs text-gray-500">
						Tests agent: <span class="font-medium text-gray-700">{{ suite.agent_name || suite.agent_configuration || "none" }}</span>
						— its provider, model and system prompt are used.
					</div>
					<FormControl label="Title" v-model="caseForm.title" />
					<FormControl type="textarea" label="User prompt" v-model="caseForm.input_user_prompt" />
					<FormControl type="textarea" label="Expected output (optional)" v-model="caseForm.expected_output" />

					<!-- Assertions -->
					<div class="border-t pt-3">
						<div class="flex items-center justify-between mb-2">
							<span class="text-sm font-semibold text-gray-700">Assertions</span>
							<Button variant="subtle" icon-left="plus" @click="addAssertion">Add assertion</Button>
						</div>
						<p v-if="!caseForm.assertions.length" class="text-xs text-amber-600 mb-2">
							A case with no assertions passes trivially — add at least one.
						</p>
						<div v-for="(a, i) in caseForm.assertions" :key="i" class="border border-gray-100 rounded-md p-3 mb-2 space-y-2">
							<div class="flex items-center gap-2">
								<FormControl type="select" :options="assertionTypeOptions" v-model="a.assertion_type" class="w-40" />
								<Button variant="ghost" icon-left="trash-2" @click="removeAssertion(i)" />
							</div>
							<FormControl
								type="textarea"
								:label="a.assertion_type === 'llm_judge' ? 'Rubric' : 'Expected value / pattern'"
								v-model="a.value"
							/>
							<div v-if="a.assertion_type === 'llm_judge'" class="grid grid-cols-3 gap-2">
								<FormControl type="select" label="Judge provider" :options="providerOptions" v-model="a.judge_provider" />
								<FormControl type="select" label="Judge model" :options="aiModelOptions" v-model="a.judge_model" />
								<FormControl type="number" label="Pass threshold (1–5)" v-model="a.pass_threshold" />
							</div>
						</div>
					</div>
				</div>
			</template>
			<template #actions>
				<div class="w-full space-y-2">
					<p v-if="caseError" class="text-sm text-red-600">{{ caseError }}</p>
					<p v-else-if="incompleteAssertion !== -1" class="text-sm text-amber-600">
						Assertion {{ incompleteAssertion + 1 }} needs
						{{ caseForm.assertions[incompleteAssertion].assertion_type === 'llm_judge' ? 'a rubric' : 'an expected value' }}.
					</p>
					<Button
						variant="solid"
						:loading="savingCase"
						:disabled="!caseForm.title || incompleteAssertion !== -1"
						@click="saveCase"
					>
						{{ caseMode === 'edit' ? 'Save changes' : 'Create case' }}
					</Button>
				</div>
			</template>
		</Dialog>

		<!-- From run modal -->
		<Dialog v-model="showFromRun" :options="{ title: 'Create case from a run' }">
			<template #body-content>
				<div class="space-y-3">
					<p v-if="loadingAgentRuns" class="text-sm text-gray-500">Loading runs…</p>
					<p v-else-if="!agentRuns.length" class="text-sm text-gray-500">
						No runs to build a case from yet — this suite's agent has not run outside
						the eval system.
					</p>
					<FormControl
						v-else
						type="select"
						label="AI Agent Run"
						:options="agentRunOptions"
						v-model="fromRun.run_name"
						@change="onRunPicked"
					/>
					<p v-if="loadingSteps" class="text-xs text-gray-500">Loading steps…</p>
					<FormControl v-if="runSteps.length" type="select" label="Step (optional)" :options="stepOptions" v-model="fromRun.step_name" />
				</div>
			</template>
			<template #actions>
				<Button variant="solid" :loading="savingFromRun" @click="createFromRun">Create case</Button>
			</template>
		</Dialog>
	</div>
</template>

<script setup>
import { ref, reactive, computed, onMounted, watch } from "vue"
import { useRoute } from "vue-router"
import { frappeRequest, Button, Dialog, FormControl } from "frappe-ui"

const route = useRoute()
const suiteName = route.params.suite

const ASSERTION_TYPES = ["contains", "regex", "equals", "schema_valid", "llm_judge"]
const assertionTypeOptions = ASSERTION_TYPES.map((t) => ({ label: t, value: t }))

const loading = ref(true)
const loadError = ref("")
const suite = ref({})
const cases = ref([])
const runs = ref([])
const metrics = ref({})
const selected = ref([])
const runningCase = reactive({})
const runningSelected = ref(false)
const runningSuite = ref(false)

const providerOptions = ref([])
const aiModelOptions = ref([])

const showCaseEditor = ref(false)
const caseMode = ref("new")
const savingCase = ref(false)
const caseError = ref("")
// value carries the whole meaning of an assertion — the rubric for llm_judge,
// the substring for contains — and is mandatory on the doctype. Catch it here so
// the button explains itself instead of the save failing at the server.
const incompleteAssertion = computed(() =>
	caseForm.assertions.findIndex((a) => !(a.value || "").trim())
)
const caseForm = reactive({
	name: "", title: "", input_user_prompt: "", expected_output: "", assertions: [],
})

const showFromRun = ref(false)
const loadingSteps = ref(false)
const savingFromRun = ref(false)
const runSteps = ref([])
const fromRun = reactive({ run_name: "", step_name: "" })

// Candidate AI Agent Runs for the "From run" picker. Distinct from `runs`
// above, which is this suite's own EVAL runs.
const agentRuns = ref([])
const loadingAgentRuns = ref(false)

// Re-check (replay) re-evaluates assertions against each case's last stored
// answer instead of calling the agent again — what you want after editing an
// assertion. It needs a prior result to read, so it is offered only once the
// suite has been run at least once.
const rechecking = ref(false)
const recheckingCase = reactive({})
const canRecheck = computed(() => runs.value.length > 0)

const _fmt = new Intl.NumberFormat("en-US")
const _fmtCost = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", minimumFractionDigits: 2, maximumFractionDigits: 4 })
function fmt(n) { return _fmt.format(n || 0) }
function fmtCost(n) { return _fmtCost.format(n || 0) }

const allSelected = computed(() => cases.value.length > 0 && selected.value.length === cases.value.length)
const stepOptions = computed(() =>
	[{ label: "(whole run)", value: "" }].concat(runSteps.value.map((s) => ({ label: s.label || s.name, value: s.name })))
)
// "2 Aug, 15:29 · Notify Assignee · Success" — when it ran, what produced it,
// and whether it worked. Enough to tell two runs apart without a second column.
const agentRunOptions = computed(() =>
	[{ label: "Select a run…", value: "" }].concat(
		agentRuns.value.map((r) => ({
			label: `${r.when} · ${r.source} · ${r.status}`,
			value: r.name,
		}))
	)
)
const sparkPoints = computed(() => {
	const s = metrics.value.sparkline
	if (!s || s.length < 2) return null
	const step = 100 / (s.length - 1)
	return s.map((v, i) => `${(i * step).toFixed(1)},${(20 - (v / 100) * 20).toFixed(1)}`).join(" ")
})

function runPill(status) {
	if (status === "Passed") return "bg-green-50 text-green-700"
	if (status === "Failed" || status === "Error") return "bg-red-50 text-red-700"
	if (status === "Running") return "bg-yellow-50 text-yellow-700 animate-pulse"
	return "bg-gray-100 text-gray-500"
}

function toggleAll(e) {
	selected.value = e.target.checked ? cases.value.map((c) => c.name) : []
}

// Frappe puts the useful text in _server_messages / exception; e.message is
// often just "<endpoint> PermissionError", which tells the user nothing.
function errorText(e, fallback) {
	const raw = e?.messages?.length ? e.messages.join(" ") : ""
	const exc = e?.exc_type && e?._error_message ? e._error_message : ""
	return raw || exc || e?.message || fallback
}

async function fetchDetail(silent = false) {
	if (!silent) loading.value = true
	loadError.value = ""
	try {
		const res = await frappeRequest({
			url: "/api/method/one_bpmn.api.eval_api.get_suite_detail",
			method: "GET",
			params: { suite: suiteName },
		})
		suite.value = res?.suite || {}
		cases.value = res?.cases || []
		runs.value = res?.runs || []
		metrics.value = res?.metrics || {}
	} catch (e) {
		console.error("Failed to load suite:", e)
		if (!silent) loadError.value = errorText(e, "Failed to load this suite.")
	} finally {
		if (!silent) loading.value = false
	}
}

function sleep(ms) { return new Promise((r) => setTimeout(r, ms)) }

// Poll quietly (no skeleton flicker) until the run leaves "Running".
async function pollRun(runName) {
	for (let i = 0; i < 40; i++) {
		await sleep(1500)
		await fetchDetail(true)
		const r = runs.value.find((x) => x.name === runName)
		if (!r || r.status !== "Running") break
	}
}

async function fetchProviders() {
	try {
		const res = await frappeRequest({
			url: "/api/method/frappe.client.get_list",
			method: "GET",
			params: { doctype: "AI Provider Credentials", filters: JSON.stringify({ enabled: 1 }), fields: JSON.stringify(["name"]), limit_page_length: 0 },
		})
		providerOptions.value = (res || []).map((p) => ({ label: p.name, value: p.name }))
	} catch (e) {
		providerOptions.value = []
	}
}

async function fetchAiModels() {
	try {
		const res = await frappeRequest({
			url: "/api/method/frappe.client.get_list",
			method: "GET",
			params: { doctype: "AI Model", fields: JSON.stringify(["name"]), limit_page_length: 0 },
		})
		aiModelOptions.value = (res || []).map((m) => ({ label: m.name, value: m.name }))
	} catch (e) {
		aiModelOptions.value = []
	}
}

function optimisticRun(runName, totalCases) {
	// Show the run immediately so there's no dead time after the click.
	runs.value.unshift({
		name: runName, display_title: "Run — starting…", status: "Running",
		passed_cases: 0, total_cases: totalCases, started_at: "",
	})
}

async function runCases(caseNames, flag, backend = "live") {
	flag.value = true
	loadError.value = ""
	try {
		const runName = await frappeRequest({
			url: "/api/method/one_bpmn.agents.eval_runner.run_eval_cases",
			method: "POST",
			params: {
				suite_name: suiteName,
				case_names: caseNames ? JSON.stringify(caseNames) : null,
				backend,
			},
		})
		optimisticRun(runName, caseNames ? caseNames.length : cases.value.length)
		pollRun(runName)
	} catch (e) {
		console.error("Run failed:", e)
		loadError.value = errorText(e, "Failed to start the run.")
	} finally {
		flag.value = false
	}
}

watch(showFromRun, (open) => {
	if (open) loadAgentRuns()
})

function runWholeSuite() { return runCases(null, runningSuite) }
function runSelected() { return runCases(selected.value, runningSelected) }

// Re-check = the replay backend: no new agent call, assertions re-evaluated
// against each case's last stored answer.
function recheckSuite() { return runCases(null, rechecking, "replay") }
async function recheckCase(c) {
	recheckingCase[c.name] = true
	try {
		await runCases([c.name], { value: false }, "replay")
	} finally {
		recheckingCase[c.name] = false
	}
}
async function runCase(c) {
	runningCase[c.name] = true
	try {
		const runName = await frappeRequest({
			url: "/api/method/one_bpmn.agents.eval_runner.run_eval_cases",
			method: "POST",
			params: { suite_name: suiteName, case_names: JSON.stringify([c.name]) },
		})
		optimisticRun(runName, 1)
		pollRun(runName)
	} catch (e) {
		console.error("Run failed:", e)
		loadError.value = errorText(e, "Failed to start the run.")
	} finally {
		runningCase[c.name] = false
	}
}

// ── Case editor (new + edit) ─────────────────────────────────────────────
function resetCaseForm() {
	Object.assign(caseForm, { name: "", title: "", input_user_prompt: "", expected_output: "", assertions: [] })
}
function addAssertion() {
	caseForm.assertions.push({ assertion_type: "contains", value: "", judge_provider: "", judge_model: "", pass_threshold: 4 })
}
function removeAssertion(i) {
	caseForm.assertions.splice(i, 1)
}
function openNewCase() {
	resetCaseForm()
	caseMode.value = "new"
	caseError.value = ""
	showCaseEditor.value = true
}
async function openEditCase(c) {
	caseMode.value = "edit"
	resetCaseForm()
	caseError.value = ""
	showCaseEditor.value = true
	try {
		const res = await frappeRequest({
			url: "/api/method/one_bpmn.api.eval_api.get_eval_case",
			method: "GET",
			params: { name: c.name },
		})
		Object.assign(caseForm, {
			name: res.name, title: res.title,
			input_user_prompt: res.input_user_prompt || "",
			expected_output: res.expected_output || "",
			assertions: (res.assertions || []).map((a) => ({
				assertion_type: a.assertion_type, value: a.value || "",
				judge_provider: a.judge_provider || "", judge_model: a.judge_model || "",
				pass_threshold: a.pass_threshold ?? 4,
			})),
		})
	} catch (e) {
		console.error("Failed to load case:", e)
	}
}
async function saveCase() {
	savingCase.value = true
	caseError.value = ""
	try {
		const payload = {
			title: caseForm.title, input_user_prompt: caseForm.input_user_prompt,
			expected_output: caseForm.expected_output, assertions: JSON.stringify(caseForm.assertions),
		}
		if (caseMode.value === "edit") {
			await frappeRequest({ url: "/api/method/one_bpmn.api.eval_api.update_eval_case", method: "POST", params: { name: caseForm.name, ...payload } })
		} else {
			await frappeRequest({ url: "/api/method/one_bpmn.api.eval_api.create_eval_case", method: "POST", params: { suite: suiteName, ...payload } })
		}
		showCaseEditor.value = false
		fetchDetail()
	} catch (e) {
		// Previously console.error only, so a rejected save looked like a dead
		// button: the dialog stayed open with no explanation and the reason was
		// only visible with devtools open.
		console.error("Save case failed:", e)
		caseError.value = serverMessage(e) || "Could not save the case."
	} finally {
		savingCase.value = false
	}
}

// Frappe puts the useful text in _server_messages (a JSON array of JSON
// strings); e.message is the bare exception class for a 417.
function serverMessage(e) {
	const raw = e?._server_messages || e?.exc || ""
	try {
		const parsed = JSON.parse(raw)
		const first = Array.isArray(parsed) ? parsed[0] : parsed
		const inner = typeof first === "string" ? JSON.parse(first) : first
		return (inner?.message || "").replace(/<[^>]*>/g, "").trim()
	} catch {
		return (e?.message || "").trim()
	}
}

async function loadAgentRuns() {
	loadingAgentRuns.value = true
	agentRuns.value = []
	try {
		agentRuns.value = await frappeRequest({
			url: "/api/method/one_bpmn.agents.eval_case_factory.list_runs_for_case_picker",
			method: "GET",
			params: { suite: suiteName },
		}) || []
	} catch (e) {
		console.error("Loading runs failed:", e)
		agentRuns.value = []
	} finally {
		loadingAgentRuns.value = false
	}
}

// Picking a run immediately offers its steps — the old dialog made you press
// "Load steps" as a separate action, which only ever had one sensible moment.
function onRunPicked() {
	fromRun.step_name = ""
	runSteps.value = []
	if (fromRun.run_name) loadSteps()
}

async function loadSteps() {
	loadingSteps.value = true
	try {
		const res = await frappeRequest({
			url: "/api/method/one_bpmn.agents.eval_case_factory.get_run_steps_for_case_picker",
			method: "GET",
			params: { run_name: fromRun.run_name },
		})
		runSteps.value = res || []
	} catch (e) {
		runSteps.value = []
	} finally {
		loadingSteps.value = false
	}
}

async function createFromRun() {
	savingFromRun.value = true
	try {
		await frappeRequest({
			url: "/api/method/one_bpmn.agents.eval_case_factory.create_eval_case_from_run",
			method: "POST",
			params: { run_name: fromRun.run_name, step_name: fromRun.step_name || null, suite: suiteName },
		})
		showFromRun.value = false
		fromRun.run_name = ""
		fromRun.step_name = ""
		runSteps.value = []
		fetchDetail()
	} catch (e) {
		console.error("Create from run failed:", e)
	} finally {
		savingFromRun.value = false
	}
}

onMounted(() => {
	fetchDetail()
	fetchProviders()
	fetchAiModels()
})
</script>
