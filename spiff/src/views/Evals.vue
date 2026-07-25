<template>
	<div class="h-full flex flex-col bg-gray-50">
		<!-- Header -->
		<header class="bg-white border-b px-6 py-4 flex items-center justify-between">
			<div class="flex items-center gap-3">
				<h1 class="text-xl font-semibold text-gray-900">Evals</h1>
				<span
					v-if="!loading"
					class="text-xs px-2 py-1 rounded-full"
					:class="isSystemManager ? 'bg-purple-50 text-purple-700' : 'bg-blue-50 text-blue-700'"
				>
					{{ isSystemManager ? "System Manager — all suites" : "Viewing as process owner — your suites" }}
				</span>
			</div>
			<div class="flex items-center gap-2">
				<Button icon-left="plus" @click="openNewSuite">New suite</Button>
				<Button icon-left="refresh-cw" @click="fetchSuites" :loading="loading">Refresh</Button>
			</div>
		</header>

		<!-- Content -->
		<main class="flex-1 p-6 overflow-auto">
			<div class="bg-white rounded-lg shadow-sm">
				<div class="border-b px-6 py-3 flex items-center justify-between">
					<h2 class="text-sm font-semibold text-gray-700">
						Suites <span class="text-gray-400 font-normal">({{ suites.length }})</span>
					</h2>
				</div>

				<div v-if="loading" class="p-6 space-y-3 animate-pulse">
					<div v-for="n in 3" :key="n" class="h-10 bg-gray-100 rounded"></div>
				</div>

				<div v-else-if="!suites.length" class="p-10 text-center text-gray-500">
					<Icon icon="lucide:clipboard-check" class="w-8 h-8 mx-auto mb-2 text-gray-300" />
					<p class="text-sm">No eval suites for your processes yet.</p>
				</div>

				<table v-else class="w-full text-sm">
					<thead>
						<tr class="text-left text-xs uppercase tracking-wide text-gray-500 border-b">
							<th class="px-6 py-3 font-medium">Suite</th>
							<th class="px-6 py-3 font-medium">Agent</th>
							<th class="px-6 py-3 font-medium">Cases</th>
							<th class="px-6 py-3 font-medium">Latest run</th>
							<th class="px-6 py-3 font-medium text-right">Actions</th>
						</tr>
					</thead>
					<tbody>
						<tr v-for="s in suites" :key="s.name" class="border-b border-gray-100 hover:bg-gray-50">
							<td class="px-6 py-3">
								<router-link
									:to="`/processa/evals/suite/${encodeURIComponent(s.name)}`"
									class="font-medium text-gray-900 hover:underline"
								>
									{{ s.title }}
								</router-link>
								<div class="text-xs text-gray-400">{{ s.process_model || "no process" }}</div>
							</td>
							<td class="px-6 py-3 text-gray-600">{{ s.agent_name || s.agent_configuration || "—" }}</td>
							<td class="px-6 py-3 text-gray-600">{{ s.case_count }}</td>
							<td class="px-6 py-3">
								<span class="inline-block px-2 py-0.5 rounded-full text-xs" :class="runPill(s.latest_run)">
									{{ runLabel(s.latest_run) }}
								</span>
							</td>
							<td class="px-6 py-3 text-right whitespace-nowrap">
								<Button variant="ghost" icon-left="user-cog" @click="openReassign(s)">Reassign</Button>
								<Button variant="solid" icon-left="play" :loading="running[s.name]" @click="runSuite(s)">Run</Button>
							</td>
						</tr>
					</tbody>
				</table>
			</div>
		</main>

		<!-- New suite modal -->
		<Dialog v-model="showNewSuite" :options="{ title: 'New eval suite' }">
			<template #body-content>
				<div class="space-y-3">
					<FormControl label="Title" v-model="newSuite.title" />
					<FormControl type="select" label="Process" :options="processOptions" v-model="newSuite.process_model" />
					<FormControl type="select" label="Agent" :options="agentOptions" v-model="newSuite.agent_configuration" />
				</div>
			</template>
			<template #actions>
				<Button variant="solid" :loading="savingSuite" :disabled="!newSuite.title || !newSuite.process_model" @click="createSuite">
					Create suite
				</Button>
			</template>
		</Dialog>

		<!-- Reassign modal -->
		<Dialog v-model="showReassign" :options="{ title: 'Reassign suite to an agent' }">
			<template #body-content>
				<div class="space-y-3">
					<p class="text-sm text-gray-600">{{ reassignSuite?.title }}</p>
					<FormControl type="select" label="Agent" :options="agentOptions" v-model="reassignAgent" />
				</div>
			</template>
			<template #actions>
				<Button variant="solid" :loading="savingReassign" @click="doReassign">Save</Button>
			</template>
		</Dialog>
	</div>
</template>

<script setup>
import { ref, reactive, onMounted } from "vue"
import { frappeRequest, Button, Dialog, FormControl } from "frappe-ui"
import { Icon } from "@iconify/vue"

const loading = ref(true)
const suites = ref([])
const isSystemManager = ref(false)
const running = reactive({})

const agentOptions = ref([])
const processOptions = ref([])

const showNewSuite = ref(false)
const savingSuite = ref(false)
const newSuite = reactive({ title: "", process_model: "", agent_configuration: "" })

const showReassign = ref(false)
const savingReassign = ref(false)
const reassignSuite = ref(null)
const reassignAgent = ref("")

function runLabel(run) {
	if (!run) return "never run"
	if (run.status === "Passed" || run.status === "Failed") {
		return `${run.status} · ${run.passed_cases}/${run.total_cases}`
	}
	return run.status
}

function runPill(run) {
	const status = run?.status
	if (status === "Passed") return "bg-green-50 text-green-700"
	if (status === "Failed" || status === "Error") return "bg-red-50 text-red-700"
	if (status === "Running") return "bg-yellow-50 text-yellow-700"
	return "bg-gray-100 text-gray-500"
}

async function fetchSuites() {
	loading.value = true
	try {
		const res = await frappeRequest({
			url: "/api/method/one_bpmn.api.eval_api.list_eval_suites",
			method: "GET",
		})
		suites.value = res?.suites || []
		isSystemManager.value = !!res?.is_system_manager
	} catch (e) {
		console.error("Failed to load eval suites:", e)
		suites.value = []
	} finally {
		loading.value = false
	}
}

async function fetchAgents() {
	try {
		const res = await frappeRequest({ url: "/api/method/one_bpmn.api.eval_api.list_assignable_agents", method: "GET" })
		agentOptions.value = [{ label: "— none —", value: "" }].concat(
			(res || []).map((a) => ({ label: a.agent_name || a.name, value: a.name }))
		)
	} catch (e) {
		agentOptions.value = [{ label: "— none —", value: "" }]
	}
}

async function fetchProcesses() {
	try {
		const res = await frappeRequest({ url: "/api/method/one_bpmn.api.eval_api.list_owned_processes", method: "GET" })
		processOptions.value = (res || []).map((p) => ({ label: p.name, value: p.name }))
	} catch (e) {
		processOptions.value = []
	}
}

async function runSuite(s) {
	running[s.name] = true
	try {
		await frappeRequest({
			url: "/api/method/one_bpmn.agents.eval_runner.run_eval_cases",
			method: "POST",
			params: { suite_name: s.name },
		})
		setTimeout(fetchSuites, 1500)
	} catch (e) {
		console.error("Failed to start run:", e)
	} finally {
		running[s.name] = false
	}
}

function openNewSuite() {
	Object.assign(newSuite, { title: "", process_model: "", agent_configuration: "" })
	showNewSuite.value = true
}

async function createSuite() {
	savingSuite.value = true
	try {
		await frappeRequest({
			url: "/api/method/one_bpmn.api.eval_api.create_suite",
			method: "POST",
			params: { ...newSuite },
		})
		showNewSuite.value = false
		fetchSuites()
	} catch (e) {
		console.error("Create suite failed:", e)
	} finally {
		savingSuite.value = false
	}
}

function openReassign(s) {
	reassignSuite.value = s
	reassignAgent.value = s.agent_configuration || ""
	showReassign.value = true
}

async function doReassign() {
	savingReassign.value = true
	try {
		await frappeRequest({
			url: "/api/method/one_bpmn.api.eval_api.reassign_suite",
			method: "POST",
			params: { suite: reassignSuite.value.name, agent_configuration: reassignAgent.value || null },
		})
		showReassign.value = false
		fetchSuites()
	} catch (e) {
		console.error("Reassign failed:", e)
	} finally {
		savingReassign.value = false
	}
}

onMounted(() => {
	fetchSuites()
	fetchAgents()
	fetchProcesses()
})
</script>
