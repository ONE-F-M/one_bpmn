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
					<span class="text-xs text-gray-400">{{ run.backend }}</span>
				</div>
				<router-link
					v-if="previous"
					:to="`/processa/evals/run/${encodeURIComponent(previous.name)}`"
					class="text-xs text-blue-600 hover:underline"
				>
					← {{ previous.display_title || previous.name }}
				</router-link>
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
						<span v-if="delta(res)" class="text-xs" :class="delta(res).cls">{{ delta(res).label }}</span>
					</div>
					<span class="text-xs text-gray-400">{{ res.tokens_used }} tok · ${{ (res.cost || 0).toFixed(4) }}</span>
				</div>
				<div class="px-6 py-4 space-y-4">
					<!-- Prompt under test -->
					<div v-if="res.input_user_prompt">
						<div class="flex items-center gap-2 mb-2">
							<span class="text-xs uppercase tracking-wide text-gray-500 font-medium">Prompt</span>
							<span v-if="!res.prompt_is_snapshot" class="text-xs text-amber-600" title="This run predates prompt snapshots, so the case's current prompt is shown.">
								current version
							</span>
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
							<p v-if="a.explanation" class="text-sm text-gray-600 mt-1">Judge: {{ a.explanation }}</p>
							<p v-else-if="a.message" class="text-sm text-gray-500 mt-1">{{ a.message }}</p>
						</div>
						<p v-if="!res.assertions.length" class="text-sm text-gray-400">No assertions.</p>
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
import { ref, onMounted } from "vue"
import { useRoute } from "vue-router"
import { frappeRequest } from "frappe-ui"
import { Icon } from "@iconify/vue"

const route = useRoute()
const runName = route.params.run

const loading = ref(true)
const run = ref({})
const results = ref([])
const previous = ref(null)

function runPill(status) {
	if (status === "Passed") return "bg-green-50 text-green-700"
	if (status === "Failed" || status === "Error") return "bg-red-50 text-red-700"
	if (status === "Running") return "bg-yellow-50 text-yellow-700"
	return "bg-gray-100 text-gray-500"
}

function delta(res) {
	const prev = previous.value?.case_status?.[res.eval_case]
	if (!prev || prev === res.status) return null
	if (res.status === "Passed" && prev === "Failed") return { label: "▲ improved", cls: "text-green-600" }
	if (res.status === "Failed" && prev === "Passed") return { label: "▼ regressed", cls: "text-red-600" }
	return { label: `was ${prev}`, cls: "text-gray-400" }
}

async function fetchReview() {
	loading.value = true
	try {
		const res = await frappeRequest({
			url: "/api/method/one_bpmn.api.eval_api.get_run_review",
			method: "GET",
			params: { run: runName },
		})
		run.value = res?.run || {}
		results.value = res?.results || []
		previous.value = res?.previous || null
	} catch (e) {
		console.error("Failed to load run review:", e)
	} finally {
		loading.value = false
	}
}

onMounted(fetchReview)
</script>
