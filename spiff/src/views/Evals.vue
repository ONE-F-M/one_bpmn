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
			<Button icon-left="refresh-cw" @click="fetchSuites" :loading="loading">Refresh</Button>
		</header>

		<!-- Content -->
		<main class="flex-1 p-6 overflow-auto">
			<div class="bg-white rounded-lg shadow-sm">
				<div class="border-b px-6 py-3 flex items-center justify-between">
					<h2 class="text-sm font-semibold text-gray-700">
						Suites <span class="text-gray-400 font-normal">({{ suites.length }})</span>
					</h2>
				</div>

				<!-- Loading -->
				<div v-if="loading" class="p-6 space-y-3 animate-pulse">
					<div v-for="n in 3" :key="n" class="h-10 bg-gray-100 rounded"></div>
				</div>

				<!-- Empty -->
				<div v-else-if="!suites.length" class="p-10 text-center text-gray-500">
					<Icon icon="lucide:clipboard-check" class="w-8 h-8 mx-auto mb-2 text-gray-300" />
					<p class="text-sm">No eval suites for your processes yet.</p>
				</div>

				<!-- Table -->
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
						<tr
							v-for="s in suites"
							:key="s.name"
							class="border-b border-gray-100 hover:bg-gray-50"
						>
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
								<span
									class="inline-block px-2 py-0.5 rounded-full text-xs"
									:class="runPill(s.latest_run)"
								>
									{{ runLabel(s.latest_run) }}
								</span>
							</td>
							<td class="px-6 py-3 text-right">
								<Button
									variant="solid"
									icon-left="play"
									:loading="running[s.name]"
									@click="runSuite(s)"
								>
									Run
								</Button>
							</td>
						</tr>
					</tbody>
				</table>
			</div>
		</main>
	</div>
</template>

<script setup>
import { ref, reactive, onMounted } from "vue"
import { frappeRequest, Button } from "frappe-ui"
import { Icon } from "@iconify/vue"

const loading = ref(true)
const suites = ref([])
const isSystemManager = ref(false)
const running = reactive({})

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

async function runSuite(s) {
	running[s.name] = true
	try {
		await frappeRequest({
			url: "/api/method/one_bpmn.agents.eval_runner.run_eval_cases",
			method: "POST",
			params: { suite_name: s.name },
		})
		// The run is enqueued; give it a moment then refresh the summary.
		setTimeout(fetchSuites, 1500)
	} catch (e) {
		console.error("Failed to start run:", e)
	} finally {
		running[s.name] = false
	}
}

onMounted(fetchSuites)
</script>
