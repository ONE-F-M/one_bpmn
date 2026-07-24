<template>
	<div class="h-full flex flex-col bg-gray-50">
		<!-- Header -->
		<header class="bg-white border-b px-6 py-4">
			<router-link to="/processa/evals" class="text-xs text-gray-500 hover:underline">← Evals</router-link>
			<div class="flex items-center justify-between mt-1">
				<div>
					<h1 class="text-xl font-semibold text-gray-900">{{ suite.title || suiteName }}</h1>
					<div class="text-xs text-gray-400">
						{{ suite.agent_name || suite.agent_configuration || "no agent" }} ·
						{{ suite.process_model || "no process" }}
					</div>
				</div>
				<div class="flex items-center gap-2">
					<Button icon-left="file-plus" @click="showNewCase = true">New case</Button>
					<Button icon-left="git-branch" @click="showFromRun = true">From run</Button>
					<Button
						variant="subtle"
						icon-left="play"
						:disabled="!selected.length"
						:loading="runningSelected"
						@click="runSelected"
					>
						Run selected ({{ selected.length }})
					</Button>
					<Button variant="solid" icon-left="play" :loading="runningSuite" @click="runWholeSuite">
						Run suite
					</Button>
				</div>
			</div>
		</header>

		<main class="flex-1 p-6 overflow-auto space-y-6">
			<div v-if="loadError" class="bg-red-50 text-red-700 text-sm rounded-lg px-4 py-3">
				{{ loadError }}
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
							<th class="px-4 py-3 font-medium">Model</th>
							<th class="px-4 py-3 font-medium text-right">Actions</th>
						</tr>
					</thead>
					<tbody>
						<tr v-for="c in cases" :key="c.name" class="border-b border-gray-100 hover:bg-gray-50">
							<td class="px-4 py-3"><input type="checkbox" :value="c.name" v-model="selected" /></td>
							<td class="px-4 py-3">
								<div class="font-medium text-gray-900">{{ c.title }}</div>
								<div v-if="c.source_run" class="text-xs text-gray-400">from {{ c.source_run }}</div>
							</td>
							<td class="px-4 py-3">
								<span
									v-for="t in c.assertion_types"
									:key="t"
									class="inline-block px-2 py-0.5 rounded-full text-xs bg-gray-100 text-gray-600 mr-1"
								>{{ t }}</span>
								<span v-if="!c.assertion_types.length" class="text-gray-400">—</span>
							</td>
							<td class="px-4 py-3 text-gray-600">{{ c.model }}</td>
							<td class="px-4 py-3 text-right">
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

		<!-- New case modal -->
		<Dialog v-model="showNewCase" :options="{ title: 'New eval case' }">
			<template #body-content>
				<div class="space-y-3">
					<FormControl label="Title" v-model="newCase.title" />
					<FormControl type="select" label="Provider" :options="providerOptions" v-model="newCase.provider" />
					<FormControl label="Model" v-model="newCase.model" placeholder="e.g. claude-haiku-4-5-20251001" />
					<FormControl type="textarea" label="System prompt" v-model="newCase.input_system_prompt" />
					<FormControl type="textarea" label="User prompt" v-model="newCase.input_user_prompt" />
					<FormControl type="textarea" label="Expected output (optional)" v-model="newCase.expected_output" />
				</div>
			</template>
			<template #actions>
				<Button variant="solid" :loading="savingCase" @click="createCase">Create case</Button>
			</template>
		</Dialog>

		<!-- From run modal -->
		<Dialog v-model="showFromRun" :options="{ title: 'Create case from a run' }">
			<template #body-content>
				<div class="space-y-3">
					<FormControl label="AI Agent Run" v-model="fromRun.run_name" placeholder="AI Agent Run name" />
					<Button variant="subtle" :loading="loadingSteps" @click="loadSteps">Load steps</Button>
					<FormControl
						v-if="runSteps.length"
						type="select"
						label="Step (optional)"
						:options="stepOptions"
						v-model="fromRun.step_name"
					/>
				</div>
			</template>
			<template #actions>
				<Button variant="solid" :loading="savingFromRun" @click="createFromRun">Create case</Button>
			</template>
		</Dialog>
	</div>
</template>

<script setup>
import { ref, reactive, computed, onMounted } from "vue"
import { useRoute } from "vue-router"
import { frappeRequest, Button, Dialog, FormControl } from "frappe-ui"

const route = useRoute()
const suiteName = route.params.suite

const loading = ref(true)
const loadError = ref("")
const suite = ref({})
const cases = ref([])
const runs = ref([])
const selected = ref([])
const runningCase = reactive({})
const runningSelected = ref(false)
const runningSuite = ref(false)

const providerOptions = ref([])
const showNewCase = ref(false)
const savingCase = ref(false)
const newCase = reactive({ title: "", provider: "", model: "", input_system_prompt: "", input_user_prompt: "", expected_output: "" })

const showFromRun = ref(false)
const loadingSteps = ref(false)
const savingFromRun = ref(false)
const runSteps = ref([])
const fromRun = reactive({ run_name: "", step_name: "" })

const allSelected = computed(() => cases.value.length > 0 && selected.value.length === cases.value.length)
const stepOptions = computed(() =>
	[{ label: "(whole run)", value: "" }].concat(runSteps.value.map((s) => ({ label: s.label || s.name, value: s.name })))
)

function runPill(status) {
	if (status === "Passed") return "bg-green-50 text-green-700"
	if (status === "Failed" || status === "Error") return "bg-red-50 text-red-700"
	if (status === "Running") return "bg-yellow-50 text-yellow-700"
	return "bg-gray-100 text-gray-500"
}

function toggleAll(e) {
	selected.value = e.target.checked ? cases.value.map((c) => c.name) : []
}

async function fetchDetail() {
	loading.value = true
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
	} catch (e) {
		console.error("Failed to load suite:", e)
		loadError.value = e?.message || String(e) || "Failed to load this suite."
	} finally {
		loading.value = false
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

async function runCases(caseNames, flag) {
	flag.value = true
	try {
		await frappeRequest({
			url: "/api/method/one_bpmn.agents.eval_runner.run_eval_cases",
			method: "POST",
			params: { suite_name: suiteName, case_names: caseNames ? JSON.stringify(caseNames) : null },
		})
		setTimeout(fetchDetail, 1500)
	} catch (e) {
		console.error("Run failed:", e)
	} finally {
		flag.value = false
	}
}

function runWholeSuite() { return runCases(null, runningSuite) }
function runSelected() { return runCases(selected.value, runningSelected) }
async function runCase(c) {
	runningCase[c.name] = true
	try {
		await frappeRequest({
			url: "/api/method/one_bpmn.agents.eval_runner.run_eval_cases",
			method: "POST",
			params: { suite_name: suiteName, case_names: JSON.stringify([c.name]) },
		})
		setTimeout(fetchDetail, 1500)
	} finally {
		runningCase[c.name] = false
	}
}

async function createCase() {
	savingCase.value = true
	try {
		await frappeRequest({
			url: "/api/method/one_bpmn.api.eval_api.create_eval_case",
			method: "POST",
			params: { suite: suiteName, ...newCase },
		})
		showNewCase.value = false
		Object.assign(newCase, { title: "", provider: "", model: "", input_system_prompt: "", input_user_prompt: "", expected_output: "" })
		fetchDetail()
	} catch (e) {
		console.error("Create case failed:", e)
	} finally {
		savingCase.value = false
	}
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
})
</script>
