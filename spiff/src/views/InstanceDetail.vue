<template>
	<div class="h-full flex flex-col bg-gray-50">
		<InstanceHeader :details="details" />

		<main class="flex-1 flex flex-col overflow-hidden">
			<div v-if="loading" class="flex justify-center flex-col items-center p-12 gap-4 flex-1">
				<Icon icon="lucide:loader" class="w-8 h-8 text-gray-400 animate-spin" />
				<span class="text-gray-500">Loading details...</span>
			</div>

			<template v-else-if="details">
				<!-- Diagram (60%) -->
				<BpmnDiagramViewer
					:xml="bpmnXml"
					:details="details"
					:logs="logs"
					:active-tasks="activeTasks"
					:selected-bpmn-id="selectedBpmnId"
					@element-select="onDiagramSelect"
					@clear-selection="clearSelection"
				/>

				<!-- Task error banner -->
				<div v-if="taskError" class="flex items-start gap-3 bg-red-50 border border-red-200 text-red-800 text-sm px-4 py-3 mx-4 mt-2 rounded-lg">
					<svg class="w-4 h-4 mt-0.5 flex-shrink-0 text-red-500" viewBox="0 0 24 24" fill="currentColor">
						<path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm1 15h-2v-2h2v2zm0-4h-2V7h2v6z"/>
					</svg>
					<div class="flex-1">
						<p class="font-semibold">Task Not Completed</p>
						<p class="mt-0.5">{{ taskError }}</p>
					</div>
					<button class="text-red-400 hover:text-red-600" @click="taskError = null">
						<svg class="w-4 h-4" viewBox="0 0 24 24" fill="currentColor"><path d="M19 6.41L17.59 5 12 10.59 6.41 5 5 6.41 10.59 12 5 17.59 6.41 19 12 13.41 17.59 19 19 17.59 13.41 12z"/></svg>
					</button>
				</div>

				<!-- Three-column bottom panel (40%) -->
				<div class="flex overflow-hidden border-t" style="height: 40%; min-height: 200px;">
					<InstanceHistory
						:task-list="taskList"
						:selected-node-id="selectedNodeId"
						:selected-bpmn-id="selectedBpmnId"
						@select="onHistorySelect"
					/>
					<ElementInspector :selected-node="selectedNode" :process-instance-name="instanceId" />
					<PendingActions
						:active-tasks="activeTasks"
						:completing-task="completingTask"
						:completing-action="completingAction"
						@complete="completeTask"
					/>
				</div>
			</template>
		</main>
	</div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from "vue"
import { useRoute } from "vue-router"
import { frappeRequest } from "frappe-ui"
import { Icon } from "@iconify/vue"


import InstanceHeader from "@/components/process_instance/InstanceHeader.vue"
import BpmnDiagramViewer from "@/components/process_instance/BpmnDiagramViewer.vue"
import InstanceHistory from "@/components/process_instance/InstanceHistory.vue"
import ElementInspector from "@/components/process_instance/ElementInspector.vue"
import PendingActions from "@/components/process_instance/PendingActions.vue"

const route = useRoute()
const instanceId = computed(() => route.params.instance)

// ── State ──

const loading = ref(true)
const details = ref(null)
const activeTasks = ref([])
const completingTask = ref(null)
const completingAction = ref(null)
const taskError = ref(null)
const logs = ref([])
const bpmnXml = ref(null)
const limitStart = ref(0)
const limitPageLength = 20
const hasMoreLogs = ref(true)
const logsLoading = ref(false)

// Selection state
const selectedBpmnId = ref(null)
const selectedNodeId = ref(null)

// ── Task list from workflow_state ──

const TASK_STATE_LABELS = {
	1: "Future", 2: "Likely", 4: "Maybe", 8: "Waiting",
	16: "Ready", 32: "Started", 64: "Completed", 128: "Cancelled", 256: "Error",
}

function getStateLabel(s) {
	return TASK_STATE_LABELS[s] || "Unknown"
}

// Task states the inspector can select: WAITING (8), READY (16) and
// STARTED (32) are included so in-flight elements — an AI Task Selector
// deciding, a user task pending — are inspectable, not just finished ones
// (COMPLETED 64, ERROR 128, CANCELLED 256).
const REACHED_STATES = new Set([8, 16, 32, 64, 128, 256])

// Service Task extensions (serviceType, etc.) are extracted at compile time and
// embedded in serialized_spec, keyed by BPMN element id. SpiffWorkflow's own
// task_spec serialization does NOT carry the spiffworkflow:* attributes, so this
// is the authoritative source for identifying AI Agent tasks (serviceType === "ai_agent").
const serviceTaskExtensions = computed(() => {
	if (!details.value?.serialized_spec) return {}
	try {
		const spec = typeof details.value.serialized_spec === "string"
			? JSON.parse(details.value.serialized_spec)
			: details.value.serialized_spec
		return spec?.service_task_extensions || {}
	} catch (e) {
		console.warn("Failed to parse serialized_spec:", e)
		return {}
	}
})

const taskList = computed(() => {
	if (!details.value?.workflow_state) return []
	try {
		const wfState = typeof details.value.workflow_state === "string"
			? JSON.parse(details.value.workflow_state)
			: details.value.workflow_state
		const subprocesses = wfState.subprocesses || {}
		const subprocessSpecs = wfState.subprocess_specs || {}

		// SpiffWorkflow drains a task's own data into its containing scope on
		// completion, so per-task data is usually {} — fall back to the
		// scope's variables (subprocess data for inner tasks, workflow data
		// at top level) so the Variables tab shows what was in scope.
		const SCOPE_SKIP = new Set(["data_objects", "doc"])
		const scopeVars = (scope) =>
			Object.fromEntries(
				Object.entries(scope || {}).filter(([k]) => !SCOPE_SKIP.has(k))
			)

		// Recursive: a task whose id keys an entry in wfState.subprocesses is
		// a Sub-Process / Ad-hoc parent — its inner tasks are flattened in
		// right after it with depth+1, each clickable like any other node.
		const buildNodes = (tasksDict, taskSpecs, depth, scopeData) => {
			const nodes = []
			for (const [uuid, t] of Object.entries(tasksDict || {})) {
				const specName = t.task_spec || ""
				if (!specName || specName === "Start" || specName === "End") continue
				if (specName.endsWith(".EndJoin") || specName.endsWith(".BoundaryEventSplit") || specName.includes(".BoundaryEventJoin")) continue
				if (!REACHED_STATES.has(t.state)) continue

				const specData = (taskSpecs || {})[specName] || {}
				const typename = specData.typename || "Task"
				const node = {
					id: uuid,
					bpmnId: specName,
					name: specData.bpmn_name || specData.description || specName,
					typename,
					depth,
					isPassThrough: /Gateway|Event/i.test(typename),
					lane: specData.lane || null,
					state: t.state || 0,
					stateLabel: getStateLabel(t.state || 0),
					timestamp: t.last_state_change ? new Date(t.last_state_change * 1000) : null,
					data: Object.keys(t.data || {}).length ? t.data : scopeData,
					extensions: {
						...((() => { try { return typeof specData.extensions === 'string' ? JSON.parse(specData.extensions) : specData.extensions; } catch { return {}; } })() || {}),
						...(serviceTaskExtensions.value[specName] || {}),
					},
				}

				const sub = subprocesses[uuid]
				if (sub) {
					const subScope = scopeVars(sub.data)
					// The parent's meaningful variables ARE its subprocess scope
					if (Object.keys(subScope).length) node.data = subScope
					const childSpecs = (subprocessSpecs[specName] || {}).task_specs || {}
					node.childNodes = buildNodes(sub.tasks, childSpecs, depth + 1, subScope)
				}
				nodes.push(node)
			}

			// Sort siblings by timestamp, then flatten each parent's subtree
			// directly beneath it so nesting order is preserved.
			nodes.sort((a, b) => (a.timestamp || 0) - (b.timestamp || 0))
			const flat = []
			for (const n of nodes) {
				flat.push(n)
				if (n.childNodes) {
					flat.push(...n.childNodes)
					delete n.childNodes
				}
			}
			return flat
		}

		return buildNodes(wfState.tasks, wfState.spec?.task_specs || {}, 0, scopeVars(wfState.data))
	} catch (e) {
		console.warn("Failed to build task list:", e)
		return []
	}
})

// ── Selected node ──

const selectedNode = computed(() => {
	if (selectedNodeId.value) return taskList.value.find((n) => n.id === selectedNodeId.value) || null
	if (selectedBpmnId.value) return taskList.value.find((n) => n.bpmnId === selectedBpmnId.value) || null
	return null
})



// ── Selection handlers ──

function onHistorySelect(node) {
	selectedNodeId.value = node.id
	selectedBpmnId.value = node.bpmnId
}

function onDiagramSelect(bpmnId) {
	selectedBpmnId.value = bpmnId
	selectedNodeId.value = null
}

function clearSelection() {
	selectedBpmnId.value = null
	selectedNodeId.value = null
}

// ── Data loading ──

async function loadDetails() {
	try {
		const res = await frappeRequest({
			url: "/api/method/frappe.client.get",
			method: "POST",
			params: { doctype: "BPMN Process Instance", name: instanceId.value },
		})
		details.value = res
		activeTasks.value = res?.active_tasks
			? res.active_tasks.filter((t) => !t.status || t.status === "Waiting")
			: []
		if (res?.process_model) loadProcessModelXml(res.process_model)
	} catch (e) {
		console.error("Failed to load instance details:", e)
	}
}

async function loadProcessModelXml(modelName) {
	try {
		const res = await frappeRequest({
			url: "/api/method/one_bpmn.api.process_map_api.get_process_model",
			params: { name: modelName },
		})
		const data = res.message || res
		if (data?.xml_content) {
			bpmnXml.value = decodeHtmlEntities(data.xml_content)
		}
	} catch (e) {
		console.error("Failed to load process model XML:", e)
	}
}

async function loadLogs() {
	if (logsLoading.value || !hasMoreLogs.value) return
	logsLoading.value = true
	try {
		const res = await frappeRequest({
			url: "/api/method/frappe.client.get_list",
			method: "POST",
			params: {
				doctype: "BPMN Activity Log",
				fields: '["name", "task_id", "task_name", "action", "timestamp", "user", "data"]',
				filters: JSON.stringify({ instance: instanceId.value }),
				order_by: "timestamp desc",
				limit_start: limitStart.value,
				limit_page_length: limitPageLength,
			},
		})
		if (res?.length > 0) {
			logs.value = [...logs.value, ...res]
			limitStart.value += res.length
			if (res.length < limitPageLength) hasMoreLogs.value = false
		} else {
			hasMoreLogs.value = false
		}
	} catch (e) {
		console.error("Failed to load logs:", e)
	} finally {
		logsLoading.value = false
	}
}

function decodeHtmlEntities(text) {
	const t = document.createElement("textarea")
	t.innerHTML = text
	return t.value
}

// ── Task completion ──

async function completeTask(task, detail) {
	if (completingTask.value) return
	const actionName = detail?.action || null
	const needsConfirm = detail?.confirmTransition === "true"
	const needsSignature = detail?.requireDigitalSignature === "true"

	const doComplete = async () => {
		taskError.value = null
		completingTask.value = task.task_id
		completingAction.value = actionName
		try {
			const csrfToken = window.csrf_token
				|| window.frappe?.csrf_token
				|| window.frappe?.boot?.csrf_token
				|| decodeURIComponent(document.cookie.split("; ").find(r => r.startsWith("csrf_token="))?.split("=")[1] || "")
				|| ""

			const resp = await fetch("/api/method/one_bpmn.api.instance_api.complete_task", {
				method: "POST",
				headers: {
					"Content-Type": "application/json",
					"X-Frappe-CSRF-Token": csrfToken,
				},
				body: JSON.stringify({
					instance_name: instanceId.value,
					task_id: task.task_id,
					data: actionName ? JSON.stringify({ action: actionName }) : "{}",
				}),
			})

			const payload = await resp.json().catch(() => ({}))

			if (!resp.ok) {
				// Extract the human-readable message from _server_messages
				let errMsg = "Failed to complete task. Please try again."
				try {
					const smsgs = JSON.parse(payload._server_messages || "[]")
					if (smsgs.length) {
						errMsg = JSON.parse(smsgs[0]).message || errMsg
					} else if (payload.exception) {
						const m = payload.exception.match(/(?:PermissionError|ValidationError):\s*(.+)/)
						if (m) errMsg = m[1].trim()
					}
				} catch (_) { /* keep default */ }
				taskError.value = errMsg
				return
			}

			// Success — refresh data
			logs.value = []
			limitStart.value = 0
			hasMoreLogs.value = true
			await loadDetails()
			await loadLogs()
		} catch (err) {
			taskError.value = "An unexpected error occurred. Please try again."
		} finally {
			completingTask.value = null
			completingAction.value = null
		}
	}

	const doSig = () => {
		if (needsSignature) {
			if (window.confirm("Digital Signature Required\n\nBy clicking OK you authorize this action.")) {
				doComplete()
			}
		} else {
			doComplete()
		}
	}

	if (needsConfirm) {
		const msg = actionName ? `Apply action "${actionName}"?` : "Complete task?"
		if (window.confirm(msg)) doSig()
	} else {
		doSig()
	}
}

// ── Realtime updates ──

async function handleRealtimeUpdate(data) {
	if (data?.instance_name && data.instance_name !== instanceId.value) return
	await loadDetails()
	logs.value = []
	limitStart.value = 0
	hasMoreLogs.value = true
	await loadLogs()
}

// ── Lifecycle ──

onMounted(async () => {

	await loadDetails()
	await loadLogs()
	loading.value = false
	if (window.frappe?.realtime) {
		window.frappe.realtime.on("bpmn_instance_updated", handleRealtimeUpdate)
	}
})

onUnmounted(() => {
	if (window.frappe?.realtime) {
		window.frappe.realtime.off("bpmn_instance_updated", handleRealtimeUpdate)
	}
})
</script>
