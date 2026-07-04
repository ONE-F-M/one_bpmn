<template>
	<div class="w-1/3 flex flex-col border-r bg-white overflow-hidden">
		<div class="px-4 h-10 border-b bg-gray-50/60 shrink-0 flex items-center gap-1">
			<button
				@click="activeTab = 'variables'"
				title="View process variables at this execution point"
				class="px-3 py-1 text-sm font-medium rounded-t transition-colors border-b-2"
				:class="activeTab === 'variables' ? 'border-blue-600 text-blue-700 bg-white' : 'border-transparent text-gray-500 hover:text-gray-700'"
			>
				Variables
			</button>
			<button
				@click="activeTab = 'details'"
				title="View element properties: name, type, state, and metadata"
				class="px-3 py-1 text-sm font-medium rounded-t transition-colors border-b-2"
				:class="activeTab === 'details' ? 'border-blue-600 text-blue-700 bg-white' : 'border-transparent text-gray-500 hover:text-gray-700'"
			>
				Details
			</button>
			<button
				v-if="isAiAgent"
				@click="activeTab = 'aiRun'; fetchAiRun()"
				title="View AI Agent Run details"
				class="px-3 py-1 text-sm font-medium rounded-t transition-colors border-b-2"
				:class="activeTab === 'aiRun' ? 'border-purple-600 text-purple-700 bg-white' : 'border-transparent text-gray-500 hover:text-gray-700'"
			>
				AI Run
			</button>
		</div>
		<div class="flex-1 overflow-y-auto custom-scrollbar p-4">
			<!-- AI Run Tab -->
			<div v-if="activeTab === 'aiRun'" class="text-[13px]">
				<div v-if="aiRunLoading" class="text-sm text-gray-400 italic text-center py-6">Loading...</div>
				<div v-else-if="aiRunError" class="text-sm text-red-500 text-center py-6">{{ aiRunError }}</div>
				<div v-else-if="!aiRun" class="text-sm text-gray-400 italic text-center py-6">No AI Agent Run data available</div>
				<div v-else class="space-y-3">
					<!-- Status badge -->
					<div class="flex items-center gap-2">
						<span class="text-gray-500 font-medium">Status</span>
						<span
							class="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[12px] font-semibold"
							:class="aiRun.status === 'Success' ? 'bg-green-100 text-green-700' : aiRun.status === 'Error' ? 'bg-red-100 text-red-700' : 'bg-blue-100 text-blue-700 animate-pulse'"
						>{{ aiRun.status }}</span>
					</div>

					<!-- Error details -->
					<div v-if="aiRun.status === 'Error' && aiRun.error_code" class="bg-red-50 rounded p-2 text-[12px]">
						<div><span class="font-semibold">Error:</span> {{ aiRun.error_code }}</div>
						<div v-if="aiRun.error_message" class="mt-1 text-red-600">{{ aiRun.error_message }}</div>
					</div>

					<!-- Metadata table -->
					<table class="w-full text-[13px]">
						<tbody class="divide-y divide-gray-100">
							<tr>
								<td class="py-1 pr-3 text-gray-500 font-medium whitespace-nowrap align-top">Model</td>
								<td class="py-1 text-gray-800 font-mono text-[12px]">{{ aiRun.model || '—' }}</td>
							</tr>
							<tr>
								<td class="py-1 pr-3 text-gray-500 font-medium whitespace-nowrap align-top">Provider</td>
								<td class="py-1 text-gray-800">{{ aiRun.provider || '—' }}</td>
							</tr>
							<tr>
								<td class="py-1 pr-3 text-gray-500 font-medium whitespace-nowrap align-top">Tokens</td>
								<td class="py-1 text-gray-600">
									{{ aiRun.total_prompt_tokens || 0 }} prompt / {{ aiRun.total_completion_tokens || 0 }} completion
									<div class="text-gray-500">Total: {{ aiRun.total_tokens || 0 }}</div>
								</td>
							</tr>
							<tr>
								<td class="py-1 pr-3 text-gray-500 font-medium whitespace-nowrap align-top">Est. Cost</td>
								<td class="py-1 text-gray-800 font-mono">{{ aiRun.estimated_cost ? '$' + formatCost(aiRun.estimated_cost) : '—' }}</td>
							</tr>
							<tr>
								<td class="py-1 pr-3 text-gray-500 font-medium whitespace-nowrap align-top">Duration</td>
								<td class="py-1 text-gray-800">{{ formatDuration(aiRun.duration_ms) }}</td>
							</tr>
							<tr>
								<td class="py-1 pr-3 text-gray-500 font-medium whitespace-nowrap align-top">Started</td>
								<td class="py-1 text-gray-600 text-[12px] font-mono">{{ formatDateTime(aiRun.started_at) }}</td>
							</tr>
						</tbody>
					</table>

					<!-- Steps section -->
					<div class="border-t pt-3 mt-3">
						<button
							@click="showSteps = !showSteps"
							class="flex items-center gap-1 text-purple-700 font-medium hover:text-purple-800 text-[12px]"
						>
							<Icon :icon="showSteps ? 'lucide:chevron-down' : 'lucide:chevron-right'" class="w-4 h-4" />
							Steps ({{ aiSteps.length }})
						</button>
						<div v-if="showSteps" class="mt-2 space-y-1">
							<div v-if="stepsLoading" class="text-sm text-gray-400 italic">Loading steps...</div>
							<div v-else-if="aiSteps.length === 0" class="text-sm text-gray-400 italic">No steps recorded</div>
							<div
								v-for="step in aiSteps"
								:key="step.name"
								class="border border-gray-200 rounded overflow-hidden"
							>
								<button
									@click="toggleStep(step.name)"
									class="w-full flex items-center justify-between px-2 py-1.5 text-[12px] hover:bg-gray-50"
									:class="expandedSteps.has(step.name) ? 'bg-gray-50' : ''"
								>
									<span class="flex items-center gap-1.5">
										<span
											class="inline-block px-1.5 py-0.5 rounded text-[10px] font-mono font-semibold"
											:class="roleBadgeClass(step.role)"
										>{{ step.role }}</span>
										<span class="text-gray-500">#{{ step.step_index }}</span>
										<span
											v-if="step.toolCalls && step.toolCalls.length"
											class="inline-block px-1.5 py-0.5 rounded text-[10px] font-mono bg-purple-100 text-purple-700"
											:title="step.toolCalls.map(tc => tc.tool_name).join(', ')"
										>🔧 {{ step.toolCalls.map(tc => tc.tool_name).join(", ").substring(0, 40) }}</span>
										<span class="text-gray-600 truncate max-w-[150px]">{{ step.content ? step.content.substring(0, 80) : '(empty)' }}</span>
									</span>
									<span class="text-gray-400 text-[10px] whitespace-nowrap">
									<template v-if="step.prompt_tokens">{{ step.prompt_tokens }}t in<span v-if="step.cost"> · ${{ formatCost(step.cost) }}</span></template>
									<template v-else-if="step.completion_tokens">{{ step.completion_tokens }}t out<span v-if="step.cost"> · ${{ formatCost(step.cost) }}</span></template>
									<span
										v-if="step.latency_ms"
										title="Decision latency: the model's API round-trip for this turn — not the runtime of an activated task"
									> · {{ (step.latency_ms / 1000).toFixed(1) }}s</span>
								</span>
								</button>
								<div v-if="expandedSteps.has(step.name)" class="border-t border-gray-200 px-2 py-1.5">
									<pre class="text-[11px] text-gray-600 font-mono whitespace-pre-wrap max-h-48 overflow-y-auto bg-gray-50 rounded p-2">{{ step.content || '(empty)' }}</pre>
									<!-- Tool calls made in this turn (AI Agent Tool Call rows) -->
									<div
										v-for="tc in step.toolCalls || []"
										:key="tc.tool_name + (tc.tool_result || '')"
										class="mt-1.5 border border-purple-200 rounded bg-purple-50/50 px-2 py-1.5"
									>
										<div class="flex items-center gap-1.5 text-[11px]">
											<span class="font-mono font-semibold text-purple-700">🔧 {{ tc.tool_name }}</span>
											<span v-if="tc.tool_source" class="px-1 py-0.5 rounded bg-purple-100 text-purple-600 text-[10px]">{{ tc.tool_source === 'diagram_task' ? 'diagram task' : 'registry tool' }}</span>
											<span
												class="px-1 py-0.5 rounded text-[10px]"
												:class="tc.status === 'Error' ? 'bg-red-100 text-red-700' : 'bg-green-100 text-green-700'"
											>{{ tc.status }}</span>
										</div>
										<div v-if="tc.tool_args && tc.tool_args !== '{}'" class="mt-1">
											<div class="text-[10px] uppercase tracking-wide text-gray-400">Arguments</div>
											<pre class="text-[11px] text-gray-600 font-mono whitespace-pre-wrap max-h-24 overflow-y-auto bg-white rounded p-1.5 border border-gray-100">{{ tc.tool_args }}</pre>
										</div>
										<div v-if="tc.tool_result" class="mt-1">
											<div class="text-[10px] uppercase tracking-wide text-gray-400">Result <span class="normal-case">(what the model was told)</span></div>
											<pre class="text-[11px] text-gray-600 font-mono whitespace-pre-wrap max-h-32 overflow-y-auto bg-white rounded p-1.5 border border-gray-100">{{ tc.tool_result }}</pre>
										</div>
										<div v-if="tc.outcome" class="mt-1">
											<div class="text-[10px] uppercase tracking-wide text-green-600">Outcome <span class="normal-case">(what actually happened)</span></div>
											<pre class="text-[11px] text-green-800 font-mono whitespace-pre-wrap max-h-32 overflow-y-auto bg-green-50 rounded p-1.5 border border-green-100">{{ tc.outcome }}</pre>
										</div>
									</div>
								</div>
							</div>
						</div>
					</div>
				</div>
			</div>

			<!-- Details Tab -->
			<div v-if="activeTab === 'details'">
				<div v-if="!selectedNode" class="text-sm text-gray-400 italic text-center py-6">
					<Icon icon="lucide:mouse-pointer-click" class="w-5 h-5 mx-auto mb-2 opacity-40" />
					Select an element to view details
				</div>
				<table v-else class="w-full text-[13px]">
					<tbody class="divide-y divide-gray-100">
						<tr>
							<td class="py-1.5 pr-3 text-gray-500 font-medium whitespace-nowrap align-top">Name</td>
							<td class="py-1.5 text-gray-800 font-semibold">{{ selectedNode.name }}</td>
						</tr>
						<tr>
							<td class="py-1.5 pr-3 text-gray-500 font-medium whitespace-nowrap align-top">Type</td>
							<td class="py-1.5 text-gray-800">
								<span class="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[11px] font-mono" :class="isAiAgent ? 'bg-purple-100 text-purple-700' : 'bg-gray-100 text-gray-700'">{{ displayType }}</span>
							</td>
						</tr>
						<tr>
							<td class="py-1.5 pr-3 text-gray-500 font-medium whitespace-nowrap align-top">BPMN ID</td>
							<td class="py-1.5 text-gray-600 font-mono text-[11px]">{{ selectedNode.bpmnId }}</td>
						</tr>
						<tr>
							<td class="py-1.5 pr-3 text-gray-500 font-medium whitespace-nowrap align-top">State</td>
							<td class="py-1.5">
								<span
									class="inline-flex items-center gap-1 text-[12px] font-semibold"
									:class="stateColorClass"
								>
									<Icon v-if="selectedNode.stateLabel === 'Completed'" icon="lucide:check-circle-2" class="w-3.5 h-3.5" />
									<Icon v-else-if="selectedNode.stateLabel === 'Error'" icon="lucide:alert-circle" class="w-3.5 h-3.5" />
									<Icon v-else-if="selectedNode.stateLabel === 'Cancelled'" icon="lucide:x-circle" class="w-3.5 h-3.5" />
									{{ selectedNode.stateLabel }}
								</span>
							</td>
						</tr>
						<tr>
							<td class="py-1.5 pr-3 text-gray-500 font-medium whitespace-nowrap align-top">Timestamp</td>
							<td class="py-1.5 text-gray-700 text-[12px] font-mono">{{ selectedNode.timestamp ? formatDateTime(selectedNode.timestamp) : '—' }}</td>
						</tr>
						<tr v-if="selectedNode.lane">
							<td class="py-1.5 pr-3 text-gray-500 font-medium whitespace-nowrap align-top">Lane</td>
							<td class="py-1.5 text-gray-700">{{ selectedNode.lane }}</td>
						</tr>
						<tr>
							<td class="py-1.5 pr-3 text-gray-500 font-medium whitespace-nowrap align-top">Task UUID</td>
							<td class="py-1.5 text-gray-500 font-mono text-[10px] break-all">{{ selectedNode.id }}</td>
						</tr>
					</tbody>
				</table>
			</div>

			<!-- Variables Tab -->
			<div v-else-if="activeTab === 'variables'">
				<div v-if="!selectedNode" class="text-sm text-gray-400 italic text-center py-6">
					<Icon icon="lucide:mouse-pointer-click" class="w-5 h-5 mx-auto mb-2 opacity-40" />
					Select an element to view variables
				</div>
				<div v-else-if="selectedNode.isPassThrough" class="text-sm text-gray-400 italic text-center py-6">
					<Icon icon="lucide:git-branch" class="w-5 h-5 mx-auto mb-2 opacity-40" />
					Routing element — does not modify variables
				</div>
				<div v-else-if="groupedVariables.length === 0" class="text-sm text-gray-400 italic text-center py-6">
					No variables at this execution point
				</div>
				<div v-else class="space-y-3">
					<div v-for="group in groupedVariables" :key="group.label">
						<div class="flex items-center gap-2 mb-1.5">
							<span class="text-[11px] font-semibold text-gray-600 uppercase tracking-wider">
								{{ group.label }}
							</span>
							<span class="text-[10px] text-gray-400">{{ group.vars.length }}</span>
						</div>
						<div class="space-y-0.5">
							<div
								v-for="v in group.vars"
								:key="v.key"
								class="flex items-start gap-2 py-1.5 border-b border-gray-50 last:border-0"
							>
								<span class="text-[12px] font-mono font-semibold text-gray-700 shrink-0 min-w-[100px]">{{ v.key }}</span>
								<span
									class="text-[10px] px-1 py-0.5 rounded font-mono shrink-0"
									:class="typeColorClass(v.type)"
								>{{ v.type }}</span>
								<pre
									v-if="v.type === 'object' || v.type === 'array'"
									class="text-[11px] text-gray-600 font-mono bg-gray-50 rounded p-2 overflow-x-auto max-h-40 flex-1"
								>{{ v.value }}</pre>
								<span v-else class="text-[12px] text-gray-600 font-mono break-all">{{ v.value }}</span>
							</div>
						</div>
					</div>
				</div>
			</div>
		</div>
	</div>
</template>

<script setup>
import { ref, computed, watch } from "vue"
import { Icon } from "@iconify/vue"
import { dayjs } from "@/dayjs"

const props = defineProps({
	selectedNode: { type: Object, default: null },
	processInstanceName: { type: String, default: "" },
})

const activeTab = ref("variables")

const STATE_COLORS = {
	Completed: "text-green-600",
	Error: "text-red-600",
	Cancelled: "text-gray-400",
}
const stateColorClass = computed(() => STATE_COLORS[props.selectedNode?.stateLabel] || "text-blue-600")

const TYPE_COLORS = {
	object: "bg-purple-50 text-purple-600",
	array: "bg-purple-50 text-purple-600",
	number: "bg-blue-50 text-blue-600",
	boolean: "bg-amber-50 text-amber-600",
	null: "bg-gray-50 text-gray-400",
}
function typeColorClass(type) {
	return TYPE_COLORS[type] || "bg-green-50 text-green-600"
}

function formatVar(key, val) {
	let display = val
	let type = typeof val
	if (typeof val === "object") {
		display = JSON.stringify(val, null, 2)
		type = Array.isArray(val) ? "array" : "object"
	} else {
		display = String(val)
	}
	return { key, value: display, type }
}

// Keys to skip entirely
function isInternalKey(key) {
	return key.startsWith("__") || key === "spiff__"
}

function isEmpty(val) {
	if (val === null || val === undefined || val === "") return true
	if (typeof val === "object" && Object.keys(val).length === 0) return true
	return false
}

// Category definitions
const CONTEXT_KEYS = new Set(["context_doctype", "context_docname"])
const WORKFLOW_KEYS = new Set(["action", "workflow_state", "docstatus", "status"])

function categorize(key) {
	if (CONTEXT_KEYS.has(key)) return "Context"
	if (WORKFLOW_KEYS.has(key)) return "Workflow"
	return "Data"
}

const CATEGORY_ORDER = ["Context", "Workflow", "Data"]

// All variables, grouped by category
const groupedVariables = computed(() => {
	const node = props.selectedNode
	if (!node || !node.data) return []

	const groups = {}
	for (const [key, val] of Object.entries(node.data)) {
		if (isInternalKey(key) || isEmpty(val)) continue
		const cat = categorize(key)
		if (!groups[cat]) groups[cat] = []
		groups[cat].push(formatVar(key, val))
	}

	// Sort variables within each group
	for (const cat of Object.keys(groups)) {
		groups[cat].sort((a, b) => a.key.localeCompare(b.key))
	}

	// Return in defined order, skipping empty categories
	return CATEGORY_ORDER
		.filter((label) => groups[label]?.length > 0)
		.map((label) => ({ label, vars: groups[label] }))
})

function formatDateTime(d) {
	return d ? dayjs(d).format("DD-MM-YYYY hh:mm A") : "-"
}

// ── AI Agent Run observability ───────────────────────────────────────

// Both AI element kinds have AI Agent Run observability: AI Agent Tasks
// (service tasks) and AI Task Selectors (ad-hoc subprocesses); runs are
// keyed by instance + bpmn_id either way.
const isAiAgent = computed(() => {
	const serviceType = props.selectedNode?.extensions?.serviceType
	return serviceType === "ai_agent" || serviceType === "ai_task_selector"
})

// Friendly type label — AI Agent Tasks serialize as a bare "ServiceTask",
// so surface them as "AI Agent Task" in the Details tab.
const displayType = computed(() => {
	const serviceType = props.selectedNode?.extensions?.serviceType
	if (serviceType === "ai_task_selector") return "AI Task Selector"
	if (serviceType === "ai_agent") return "AI Agent Task"
	return props.selectedNode?.typename || "—"
})

const aiRun = ref(null)
const aiRunLoading = ref(false)
const aiRunError = ref(null)
const showSteps = ref(false)
const aiSteps = ref([])
const stepsLoading = ref(false)
const expandedSteps = ref(new Set())

// Reset state when selection changes
watch(() => props.selectedNode, () => {
	if (activeTab.value !== 'aiRun') return
	fetchAiRun()
})

async function fetchAiRun() {
	aiRun.value = null
	aiSteps.value = []
	expandedSteps.value = new Set()
	showSteps.value = false
	aiRunError.value = null

	if (!props.selectedNode || !props.processInstanceName) return

	aiRunLoading.value = true
	try {
		const csrf = getCsrfToken()
		const bpmnId = props.selectedNode.bpmnId || props.selectedNode.id
		const params = new URLSearchParams({
			doctype: "AI Agent Run",
			fields: JSON.stringify(["name", "status", "model", "provider", "total_prompt_tokens", "total_completion_tokens", "total_tokens", "estimated_cost", "duration_ms", "started_at", "ended_at", "error_code", "error_message", "backend"]) ,
			filters: JSON.stringify([
				["instance", "=", props.processInstanceName],
				["bpmn_id", "=", bpmnId],
			]),
			limit_page_length: 1,
			order_by: "creation desc",
		})
		const r = await fetch(`/api/method/frappe.client.get_list?${params}`, {
			headers: { "X-Frappe-CSRF-Token": csrf },
		})
		const data = await r.json()
		const rows = data?.message || []
		if (rows.length > 0) {
			aiRun.value = rows[0]
			// Eagerly fetch steps so the count is accurate before toggle
			fetchSteps()
		}
	} catch (e) {
		aiRunError.value = "Failed to load AI Run data"
		console.error("AI Run fetch error:", e)
	} finally {
		aiRunLoading.value = false
	}
}

async function fetchSteps() {
	if (!aiRun.value?.name) return
	stepsLoading.value = true
	try {
		const csrf = getCsrfToken()
		const params = new URLSearchParams({
			doctype: "AI Agent Step",
			fields: JSON.stringify(["name", "step_index", "role", "content", "tool_name", "tool_args", "tool_result", "prompt_tokens", "completion_tokens", "cost", "latency_ms"]) ,
			filters: JSON.stringify([["run", "=", aiRun.value.name]]),
			limit_page_length: 200,
			order_by: "step_index asc",
		})
		const r = await fetch(`/api/method/frappe.client.get_list?${params}`, {
			headers: { "X-Frappe-CSRF-Token": csrf },
		})
		const data = await r.json()
		const steps = data?.message || []

		// Tool calls live in the AI Agent Tool Call child table (WI-001358) —
		// fetch them for all steps in one query and attach per step.
		if (steps.length) {
			try {
				const tcParams = new URLSearchParams({
					doctype: "AI Agent Tool Call",
					parent: "AI Agent Step",
					fields: JSON.stringify(["parent", "tool_name", "tool_source", "status", "tool_args", "tool_result", "outcome"]),
					filters: JSON.stringify([
						["parenttype", "=", "AI Agent Step"],
						["parent", "in", steps.map((s) => s.name)],
					]),
					limit_page_length: 500,
					order_by: "idx asc",
				})
				const tcRes = await fetch(`/api/method/frappe.client.get_list?${tcParams}`, {
					headers: { "X-Frappe-CSRF-Token": csrf },
				})
				const tcData = await tcRes.json()
				const byStep = {}
				for (const tc of tcData?.message || []) {
					;(byStep[tc.parent] = byStep[tc.parent] || []).push(tc)
				}
				for (const s of steps) s.toolCalls = byStep[s.name] || []
			} catch (e) {
				console.warn("AI Tool Call fetch error:", e)
			}
		}
		aiSteps.value = steps
	} catch (e) {
		console.error("AI Steps fetch error:", e)
	} finally {
		stepsLoading.value = false
	}
}

watch(showSteps, (val) => {
	if (val && aiSteps.value.length === 0) {
		fetchSteps()
	}
})

function toggleStep(name) {
	if (expandedSteps.value.has(name)) {
		expandedSteps.value.delete(name)
	} else {
		expandedSteps.value.add(name)
	}
}

function roleBadgeClass(role) {
	const map = {
		system: "bg-gray-100 text-gray-600",
		user: "bg-blue-50 text-blue-600",
		assistant: "bg-green-50 text-green-600",
		tool: "bg-amber-50 text-amber-600",
	}
	return map[role] || "bg-gray-100 text-gray-600"
}

function formatCost(val) {
	if (val === null || val === undefined) return "—"
	const n = Number(val)
	if (n < 0.01) return n.toFixed(6)
	return n.toFixed(4)
}

function formatDuration(ms) {
	if (!ms) return "—"
	if (ms < 1000) return `${ms}ms`
	if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`
	const min = Math.floor(ms / 60000)
	const sec = ((ms % 60000) / 1000).toFixed(0)
	return `${min}m ${sec}s`
}

function getCsrfToken() {
	const match = document.cookie.match(/csrf_token=([^;]+)/)
	if (match) return match[1]
	const meta = document.querySelector('meta[name="csrf-token"]')
	if (meta) return meta.getAttribute("content")
	return ""
}
</script>

<style scoped>
.custom-scrollbar::-webkit-scrollbar { width: 6px; height: 6px; }
.custom-scrollbar::-webkit-scrollbar-track { background: rgba(0,0,0,0.02); }
.custom-scrollbar::-webkit-scrollbar-thumb { background: rgba(0,0,0,0.1); border-radius: 10px; }
.custom-scrollbar::-webkit-scrollbar-thumb:hover { background: rgba(0,0,0,0.2); }
</style>
