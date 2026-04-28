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
		</div>
		<div class="flex-1 overflow-y-auto custom-scrollbar p-4">
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
								<span class="inline-flex items-center gap-1 px-2 py-0.5 rounded bg-gray-100 text-gray-700 text-[11px] font-mono">{{ selectedNode.typename }}</span>
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
			<div v-else>
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
import { ref, computed } from "vue"
import { Icon } from "@iconify/vue"
import { dayjs } from "@/dayjs"

const props = defineProps({
	selectedNode: { type: Object, default: null },
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
</script>

<style scoped>
.custom-scrollbar::-webkit-scrollbar { width: 6px; height: 6px; }
.custom-scrollbar::-webkit-scrollbar-track { background: rgba(0,0,0,0.02); }
.custom-scrollbar::-webkit-scrollbar-thumb { background: rgba(0,0,0,0.1); border-radius: 10px; }
.custom-scrollbar::-webkit-scrollbar-thumb:hover { background: rgba(0,0,0,0.2); }
</style>
