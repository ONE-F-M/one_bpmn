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

				<!-- Three-column bottom panel (40%) -->
				<div class="flex overflow-hidden border-t" style="height: 40%; min-height: 200px;">
					<InstanceHistory
						:task-list="taskList"
						:selected-node-id="selectedNodeId"
						:selected-bpmn-id="selectedBpmnId"
						@select="onHistorySelect"
					/>
					<ElementInspector :selected-node="selectedNode" />
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

const REACHED_STATES = new Set([64, 128, 256])

const taskList = computed(() => {
	if (!details.value?.workflow_state) return []
	try {
		const wfState = typeof details.value.workflow_state === "string"
			? JSON.parse(details.value.workflow_state)
			: details.value.workflow_state
		const tasks = wfState.tasks || {}
		const taskSpecs = wfState.spec?.task_specs || {}

		const nodes = []
		for (const [uuid, t] of Object.entries(tasks)) {
			const specName = t.task_spec || ""
			if (!specName || specName === "Start" || specName === "End") continue
			if (specName.endsWith(".EndJoin") || specName.endsWith(".BoundaryEventSplit") || specName.includes(".BoundaryEventJoin")) continue
			if (!REACHED_STATES.has(t.state)) continue

			const specData = taskSpecs[specName] || {}
			const typename = specData.typename || "Task"
			nodes.push({
				id: uuid,
				bpmnId: specName,
				name: specData.bpmn_name || specData.description || specName,
				typename,
				isPassThrough: /Gateway|Event/i.test(typename),
				lane: specData.lane || null,
				state: t.state || 0,
				stateLabel: getStateLabel(t.state || 0),
				timestamp: t.last_state_change ? new Date(t.last_state_change * 1000) : null,
				data: t.data || {},
				extensions: specData.extensions || {},
			})
		}

		nodes.sort((a, b) => (a.timestamp || 0) - (b.timestamp || 0))
		return nodes
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
			url: "/api/method/one_bpmn.api.get_process_model",
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
		completingTask.value = task.task_id
		completingAction.value = actionName
		try {
			await frappeRequest({
				url: "/api/method/one_bpmn.api.complete_task",
				method: "POST",
				params: {
					instance_name: instanceId.value,
					task_id: task.task_id,
					data: actionName ? JSON.stringify({ action: actionName }) : "{}",
				},
			})
			// Refresh data
			logs.value = []
			limitStart.value = 0
			hasMoreLogs.value = true
			await loadDetails()
			await loadLogs()
		} catch (err) {
			const errMsg = err.message || "Failed to complete task"
			if (window.frappe?.show_alert) {
				window.frappe.show_alert({ message: errMsg, indicator: "red" }, 5)
			} else {
				window.alert(errMsg)
			}
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
