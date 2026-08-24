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
			<button
				v-if="isAiAgent"
				@click="activeTab = 'memory'; fetchMemory()"
				title="View the agent's conversation and long-term memory"
				class="px-3 py-1 text-sm font-medium rounded-t transition-colors border-b-2"
				:class="activeTab === 'memory' ? 'border-purple-600 text-purple-700 bg-white' : 'border-transparent text-gray-500 hover:text-gray-700'"
			>
				Memory
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
											:title="step.toolCalls.map(tc => toolLabel(tc.tool_name)).join(', ')"
										>🔧 {{ step.toolCalls.map(tc => toolLabel(tc.tool_name)).join(", ").substring(0, 40) }}</span>
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
											<span class="font-semibold text-purple-700">🔧 {{ toolLabel(tc.tool_name) }}</span>
											<span v-if="toolLabel(tc.tool_name) !== tc.tool_name" class="font-mono text-[10px] text-gray-400">{{ tc.tool_name }}</span>
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

			<!-- Memory Tab -->
			<div v-if="activeTab === 'memory'" class="text-[13px]">
				<div v-if="memoryLoading" class="text-sm text-gray-400 italic text-center py-6">Loading...</div>
				<div v-else-if="memoryError" class="text-sm text-red-500 text-center py-6">{{ memoryError }}</div>
				<div v-else-if="!hasMemoryData" class="text-sm text-gray-400 italic text-center py-6">No memory data</div>
				<div v-else class="space-y-4">
					<!-- Conversation -->
					<div v-if="conversation.length">
						<div class="text-gray-500 font-medium mb-1">Conversation</div>
						<div class="space-y-1">
							<div v-for="(m, i) in conversation" :key="i" class="border border-gray-200 rounded px-2 py-1.5">
								<div class="flex items-center gap-1.5">
									<span
										class="inline-block px-1.5 py-0.5 rounded text-[10px] font-mono font-semibold"
										:class="roleBadgeClass(m.role)"
									>{{ m.role }}</span>
									<span
										v-if="m.toolCalls && m.toolCalls.length"
										class="inline-block px-1.5 py-0.5 rounded text-[10px] font-mono bg-purple-100 text-purple-700"
									>🔧 {{ m.toolCalls.length }} tool call{{ m.toolCalls.length > 1 ? 's' : '' }}</span>
								</div>
								<pre v-if="m.content" class="mt-1 text-[11px] text-gray-600 font-mono whitespace-pre-wrap max-h-40 overflow-y-auto bg-gray-50 rounded p-2">{{ m.content }}</pre>
								<div
									v-for="(tc, j) in m.toolCalls || []"
									:key="j"
									class="mt-1 border border-purple-200 rounded bg-purple-50/50 px-2 py-1"
								>
									<span class="text-[11px] font-semibold text-purple-700">🔧 {{ toolLabel(toolCallName(tc)) }}</span>
									<pre v-if="toolCallArgs(tc)" class="mt-1 text-[11px] text-gray-600 font-mono whitespace-pre-wrap max-h-24 overflow-y-auto bg-white rounded p-1.5 border border-gray-100">{{ toolCallArgs(tc) }}</pre>
								</div>
							</div>
						</div>
					</div>

					<!-- Long-term memory -->
					<div v-if="memoryGroups.length">
						<div class="text-gray-500 font-medium mb-1">Long-term memory</div>
						<div v-for="group in memoryGroups" :key="group.label" class="mb-2">
							<div class="text-[10px] uppercase tracking-wide text-gray-400 mb-1">{{ group.label }}</div>
							<div
								v-for="mem in group.items"
								:key="mem.name"
								class="border border-gray-200 rounded px-2 py-1.5 mb-1"
							>
								<pre class="text-[11px] text-gray-700 whitespace-pre-wrap max-h-32 overflow-y-auto">{{ mem.content }}</pre>
								<div v-if="mem.metadata && mem.metadata !== '{}'" class="mt-1">
									<div class="text-[10px] uppercase tracking-wide text-gray-400">Metadata</div>
									<pre class="text-[11px] text-gray-500 font-mono whitespace-pre-wrap max-h-24 overflow-y-auto bg-gray-50 rounded p-1.5">{{ mem.metadata }}</pre>
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
							<td class="py-1.5 text-gray-600 font-mono text-[11px]">{{ selectedNode.bpmnId || selectedNode.toolBpmnId || "—" }}</td>
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
import { frappeRequest } from "frappe-ui"
import { Icon } from "@iconify/vue"
import { dayjs } from "@/dayjs"

const props = defineProps({
	selectedNode: { type: Object, default: null },
	processInstanceName: { type: String, default: "" },
	// bpmnId → shape label, from the instance's workflow state. Tool names
	// are BPMN IDs for diagram tasks; registry tools won't be in the map
	// and fall back to their own name.
	taskLabels: { type: Object, default: () => ({}) },
	// WI-001426: bumped when an AI tool-call history row is clicked —
	// forces the AI Run tab open so the call's full trace is in view.
	openAiRunTick: { type: Number, default: 0 },
})

function toolLabel(toolName) {
	return props.taskLabels[toolName] || toolName
}

const activeTab = ref("variables")

watch(() => props.openAiRunTick, (tick) => {
	if (!tick) return
	activeTab.value = "aiRun"
	fetchAiRun()
})

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
	if (serviceType === "ai_agent" || serviceType === "ai_task_selector") return true
	// A tool-call row for a shape that now dispatches its own tracked LLM
	// call (e.g. classify_intent routing through execute_shape/dispatch_ai_agent)
	// carries a real aiRunName even though it never gets extensions.serviceType
	// — on the diagram it's still a plain Script Task, not a Service Task.
	// Unlock the same tabs whenever there's an actual run to show.
	return Boolean(props.selectedNode?.isAiToolCall && props.selectedNode?.aiRunName)
})

// Friendly type label — AI Agent Tasks serialize as a bare "ServiceTask",
// so surface them as "AI Agent Task" in the Details tab.
const displayType = computed(() => {
	const serviceType = props.selectedNode?.extensions?.serviceType
	if (serviceType === "ai_task_selector") return "AI Task Selector"
	if (serviceType === "ai_agent") return "AI Agent Task"
	if (props.selectedNode?.isAiToolCall) {
		return props.selectedNode?.aiRunName ? "AI Tool Call (tracked)" : "AI Tool Call"
	}
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
	if (activeTab.value === 'aiRun') fetchAiRun()
	else if (activeTab.value === 'memory') fetchMemory()
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
		const bpmnId = props.selectedNode.bpmnId || props.selectedNode.id
		// A history-row selection carries its visit's own run name (stamped by
		// the task-list flattener): a looping process executes the same shape
		// once per turn, so "latest run for the shape" would show every visit
		// identical data. Diagram-shape selections have no visit — latest is
		// the right answer there.
		const runFilter = props.selectedNode.aiRunName
			? [["name", "=", props.selectedNode.aiRunName]]
			: [
					["instance", "=", props.processInstanceName],
					["bpmn_id", "=", bpmnId],
				]
		const rows = await frappeRequest({
			url: "/api/method/frappe.client.get_list",
			params: {
				doctype: "AI Agent Run",
				fields: JSON.stringify(["name", "status", "model", "provider", "total_prompt_tokens", "total_completion_tokens", "total_tokens", "estimated_cost", "duration_ms", "started_at", "ended_at", "error_code", "error_message", "backend"]),
				filters: JSON.stringify(runFilter),
				limit_page_length: 1,
				order_by: "creation desc",
			},
		})
		if (rows?.length > 0) {
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
		const steps = (await frappeRequest({
			url: "/api/method/frappe.client.get_list",
			params: {
				doctype: "AI Agent Step",
				fields: JSON.stringify(["name", "step_index", "role", "content", "prompt_tokens", "completion_tokens", "cost", "latency_ms"]),
				filters: JSON.stringify([["run", "=", aiRun.value.name]]),
				limit_page_length: 200,
				order_by: "step_index asc",
			},
		})) || []

		// Tool calls live in the AI Agent Tool Call child table (WI-001358) —
		// fetch them for all steps in one query and attach per step.
		if (steps.length) {
			try {
				const tcRows = (await frappeRequest({
					url: "/api/method/frappe.client.get_list",
					params: {
						doctype: "AI Agent Tool Call",
						parent: "AI Agent Step",
						fields: JSON.stringify(["parent", "tool_name", "tool_source", "status", "tool_args", "tool_result", "outcome"]),
						filters: JSON.stringify([
							["parenttype", "=", "AI Agent Step"],
							["parent", "in", steps.map((s) => s.name)],
						]),
						limit_page_length: 500,
						order_by: "idx asc",
					},
				})) || []
				const byStep = {}
				for (const tc of tcRows) {
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

// ── Memory view (conversation + long-term memory) ─────────────────────
const memoryLoading = ref(false)
const memoryError = ref(null)
const conversation = ref([])   // [{ role, content, toolCalls, tool_call_id }]
const memWritten = ref([])     // AI Memory rows written by this run (source_run)
const memInScope = ref([])     // AI Memory rows in the task's scope (retrievable)

const hasMemoryData = computed(
	() => conversation.value.length || memWritten.value.length || memInScope.value.length,
)

const memoryGroups = computed(() => {
	const groups = []
	if (memWritten.value.length) groups.push({ label: "Written by this run", items: memWritten.value })
	if (memInScope.value.length) groups.push({ label: "In scope (retrievable)", items: memInScope.value })
	return groups
})

const MESSAGE_TYPE_TO_ROLE = { User: "user", Bot: "assistant", Tool: "tool" }

function normalizeMsg(m) {
	return {
		role: m.role,
		content: m.content || "",
		toolCalls: Array.isArray(m.tool_calls) ? m.tool_calls : null,
		tool_call_id: m.tool_call_id || null,
	}
}

function toolCallName(tc) {
	return tc?.name || tc?.tool_name || tc?.function?.name || "tool"
}

function toolCallArgs(tc) {
	const a = tc?.arguments ?? tc?.args ?? tc?.tool_args ?? tc?.function?.arguments
	if (a === null || a === undefined || a === "") return ""
	return typeof a === "string" ? a : JSON.stringify(a, null, 2)
}

// Shared read helper. Throws on non-OK (e.g. 403) so the caller can surface a
// clear permission message instead of crashing.
async function frappeGetList(doctype, fields, filters, extra = {}) {
	const params = {
		doctype,
		fields: JSON.stringify(fields),
		filters: JSON.stringify(filters),
		limit_page_length: extra.limit || 100,
		order_by: extra.order_by || "creation desc",
	}
	if (extra.parent) params.parent = extra.parent
	// frappeRequest throws on non-OK (e.g. 403) so the caller can surface a
	// clear permission message instead of crashing.
	return (await frappeRequest({ url: "/api/method/frappe.client.get_list", params })) || []
}

async function loadDocumentStoreConversation(bpmnId) {
	const title = `one_bpmn:${props.processInstanceName}:${bpmnId}`
	const convs = await frappeGetList("Chat Conversation", ["name"], [["title", "=", title]], { limit: 1 })
	if (!convs.length) return
	const rows = await frappeGetList(
		"Chat Message",
		["text", "message_type", "tool_calls", "tool_call_id", "metadata"],
		[["conversation", "=", convs[0].name]],
		{ limit: 500, order_by: "creation asc" },
	)
	const parsed = rows.map((r) => {
		let meta = {}
		try { meta = JSON.parse(r.metadata || "{}") } catch (e) { meta = {} }
		let toolCalls = null
		try { toolCalls = r.tool_calls ? JSON.parse(r.tool_calls) : null } catch (e) { toolCalls = null }
		return {
			seq: meta.seq ?? 0,
			role: meta.role || MESSAGE_TYPE_TO_ROLE[r.message_type] || "assistant",
			content: r.text || "",
			toolCalls: Array.isArray(toolCalls) ? toolCalls : null,
			tool_call_id: r.tool_call_id || null,
		}
	})
	parsed.sort((a, b) => a.seq - b.seq)
	conversation.value = parsed
}

// Resolve the AI Memory filters for the task's scope + scope key(s), mirroring
// the dispatcher's resolution. Returns null when the key can't be built.
async function resolveScopeFilters(bpmnId, ext) {
	const scope = ext.aiMemoryScope || "Agent"
	if (scope === "Agent") {
		const el = ext.aiMemoryAgentElement || bpmnId
		return el ? [["memory_scope", "=", "Agent"], ["agent_element", "=", el]] : null
	}
	if (scope === "Entity") {
		const data = props.selectedNode.data || {}
		const rd = data.context_doctype
		const rn = data.context_docname
		return rd && rn
			? [["memory_scope", "=", "Entity"], ["reference_doctype", "=", rd], ["reference_name", "=", rn]]
			: null
	}
	if (scope === "Process") {
		const inst = await frappeGetList("BPMN Process Instance", ["process_model"], [["name", "=", props.processInstanceName]], { limit: 1 })
		const pm = inst[0]?.process_model
		return pm ? [["memory_scope", "=", "Process"], ["process_model", "=", pm]] : null
	}
	return null
}

async function fetchMemory() {
	conversation.value = []
	memWritten.value = []
	memInScope.value = []
	memoryError.value = null

	if (!props.selectedNode || !props.processInstanceName) return

	memoryLoading.value = true
	try {
		const bpmnId = props.selectedNode.bpmnId || props.selectedNode.id
		const ext = props.selectedNode.extensions || {}

		// ── Conversation ──
		const backend = ext.aiConversationStore || "process_variable"
		if (backend === "document_store") {
			await loadDocumentStoreConversation(bpmnId)
		} else {
			// process_variable / custom: the thread lives in the viewer's task data
			const thread = (props.selectedNode.data || {})[`${bpmnId}_conversation`]
			conversation.value = Array.isArray(thread) ? thread.map(normalizeMsg) : []
		}

		// ── Long-term memory: written by this run (via source_run) ──
		let runName = aiRun.value?.name
		if (!runName) {
			const runs = await frappeGetList(
				"AI Agent Run", ["name"],
				[["instance", "=", props.processInstanceName], ["bpmn_id", "=", bpmnId]],
				{ limit: 1, order_by: "creation desc" },
			)
			runName = runs[0]?.name || null
		}
		const memFields = ["name", "content", "metadata", "memory_scope", "dedup_key"]
		if (runName) {
			memWritten.value = await frappeGetList("AI Memory", memFields, [["source_run", "=", runName]], { limit: 50, order_by: "creation desc" })
		}

		// ── Long-term memory: retrievable (task's scope + scope key) ──
		const scopeFilters = await resolveScopeFilters(bpmnId, ext)
		if (scopeFilters) {
			memInScope.value = await frappeGetList("AI Memory", memFields, scopeFilters, { limit: 50, order_by: "modified desc" })
		}
	} catch (e) {
		memoryError.value = e.status === 403
			? "You don't have permission to view this memory data."
			: "Failed to load memory data"
		console.error("Memory fetch error:", e)
	} finally {
		memoryLoading.value = false
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

</script>

<style scoped>
.custom-scrollbar::-webkit-scrollbar { width: 6px; height: 6px; }
.custom-scrollbar::-webkit-scrollbar-track { background: rgba(0,0,0,0.02); }
.custom-scrollbar::-webkit-scrollbar-thumb { background: rgba(0,0,0,0.1); border-radius: 10px; }
.custom-scrollbar::-webkit-scrollbar-thumb:hover { background: rgba(0,0,0,0.2); }
</style>
