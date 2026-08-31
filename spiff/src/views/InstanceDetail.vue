<template>
	<div class="h-full flex flex-col bg-gray-50">
		<InstanceHeader :details="details" :refreshing="refreshing" @refresh="refresh" />

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
					:ai-called-tools="aiCalledTools"
					:waiting-ai-tasks="waitingAiMap"
					@element-select="onDiagramSelect"
					@clear-selection="clearSelection"
				/>

				<!-- Waiting for AI execution (WI-001499) -->
				<div v-if="waitingForAi" class="flex items-center gap-3 bg-blue-50 border border-blue-200 text-blue-800 text-sm px-4 py-2.5 mx-4 mt-2 rounded-lg">
					<span class="text-blue-600 animate-pulse text-base leading-none">✦</span>
					<div class="flex-1">
						<span class="font-semibold">Waiting for AI execution</span>
						<span v-if="parkedAiLabels" class="text-blue-600"> — {{ parkedAiLabels }}</span>
					</div>
					<Icon icon="lucide:loader" class="w-4 h-4 text-blue-400 animate-spin" />
				</div>

				<!-- Suspended agent waiting for a person (Durable AI Agent HITL) -->
				<div v-if="waitingForHuman" class="flex items-center gap-3 bg-amber-50 border border-amber-200 text-amber-800 text-sm px-4 py-2.5 mx-4 mt-2 rounded-lg">
					<Icon icon="lucide:user-round" class="w-4 h-4 text-amber-600" />
					<div class="flex-1">
						<span class="font-semibold">AI agent waiting for a human task</span>
						<span class="text-amber-700"> — {{ waitingForHuman }}</span>
					</div>
					<span class="text-amber-500 animate-pulse text-base leading-none">✦</span>
				</div>

				<!-- AI job failed after retries (WI-001497/WI-001499) -->
				<div v-else-if="details.status === 'Errored' && parkedAiTasks.length" class="flex items-start gap-3 bg-red-50 border border-red-200 text-red-800 text-sm px-4 py-3 mx-4 mt-2 rounded-lg">
					<span class="text-red-500 text-base leading-none mt-0.5">✦</span>
					<div class="flex-1">
						<p class="font-semibold">AI execution failed</p>
						<p class="mt-0.5">The AI job for {{ parkedAiLabels }} failed after its retries. The task is still parked — retry resumes exactly where it stopped.</p>
					</div>
					<button
						class="px-3 py-1.5 rounded-md bg-blue-600 text-white text-xs font-semibold hover:bg-blue-700 disabled:opacity-50"
						:disabled="retryingAi"
						@click="retryAiTasks"
					>
						{{ retryingAi ? "Retrying…" : "Retry AI task" }}
					</button>
				</div>

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
					<ElementInspector :selected-node="selectedNode" :process-instance-name="instanceId" :task-labels="taskLabels" :open-ai-run-tick="aiRunTick" />
					<PendingActions
						:active-tasks="activeTasks"
						:completing-task="completingTask"
						:completing-action="completingAction"
						:engine-busy="engineBusy"
						@complete="completeTask"
					/>
				</div>
			</template>
		</main>
	</div>
</template>

<script setup>
import { ref, computed, watch, onMounted, onUnmounted } from "vue"
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
const refreshing = ref(false)
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
	16: "Ready", 32: "Started", 64: "Completed", 128: "Error", 256: "Cancelled",
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

		// SpiffWorkflow 1.4 serializes each task's data as a DELTA relative to
		// its parent (task.delta = { updates, deletions }); task.data itself is
		// {}. To show "variables at this execution point" we must reconstruct the
		// cumulative data by walking the parent chain from the root and applying
		// each task's delta in order. The root (Start) still carries the initial
		// data in task.data. Falls back cleanly to the pre-1.4 format, where a
		// task's data is the full accumulated dict (last-in-chain wins) or empty
		// (then baseScope — the containing workflow/subprocess scope — is used).
		const reconstructData = (uuid, tasksDict, baseScope) => {
			const chain = []
			const seen = new Set()
			let cur = uuid
			while (cur && tasksDict[cur] && !seen.has(cur)) {
				seen.add(cur)
				chain.push(tasksDict[cur])
				cur = tasksDict[cur].parent
			}
			chain.reverse()
			let data = { ...(baseScope || {}) }
			for (const node of chain) {
				if (node.data && Object.keys(node.data).length) {
					data = { ...data, ...node.data }
				}
				const delta = node.delta
				if (delta) {
					for (const [k, v] of Object.entries(delta.updates || {})) data[k] = v
					for (const k of delta.deletions || []) delete data[k]
				}
			}
			return data
		}

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
					data: reconstructData(uuid, tasksDict, scopeData),
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
			const aiVisitIdx = {} // bpmnId → agent-task visits emitted so far
			// bpmnId → dedicated-run visits consumed so far, across all parent visits.
			const toolVisitIdx = {}
			for (let i = 0; i < nodes.length; i++) {
				const n = nodes[i]
				flat.push(n)
				// WI-001426: an AI Agent Task's tool calls happen inside the
				// LLM loop, not as engine tasks — inject synthetic nested rows
				// (from ai_agent_tool_call records) so the history shows what
				// the agent did. AI Agent Runs are zipped to the task's visits
				// in chronological order, so a looping conversation shows each
				// turn's own calls, not every turn's calls under every visit.
				if (n.extensions?.serviceType === "ai_agent") {
					const runs = aiCallRunsByBpmnId.value[n.bpmnId] || []
					const visit = aiVisitIdx[n.bpmnId] || 0
					aiVisitIdx[n.bpmnId] = visit + 1
					const slot = runs[visit] || {}
					const calls = slot.calls || []
					// This visit's own AI Agent Run — the inspector's AI tab
					// fetches this exact run instead of "latest for the shape".
					n.aiRunName = slot.runName || null
					// The tools-decision gateway that follows the agent completes
					// in the same engine pass, milliseconds later. Emit it before
					// the call rows so the history reads agent → decision → tools
					// (Camunda's Operate ordering), not tools → decision.
					if (calls.length) {
						const next = nodes[i + 1]
						if (next && /Gateway/i.test(next.typename || "")) {
							flat.push(next)
							if (next.childNodes) {
								flat.push(...next.childNodes)
								delete next.childNodes
							}
							i++
						}
					}
					calls.forEach((call, ci) => {
						// Prefer the tool's own dedicated run over the parent's, when it has one.
						const ownRuns = aiCallRunsByBpmnId.value[call.tool_name] || []
						const ownVisit = toolVisitIdx[call.tool_name] || 0
						toolVisitIdx[call.tool_name] = ownVisit + 1
						const ownRun = ownRuns[ownVisit] || {}
						const ownRunName = ownRun.runName || null
						flat.push({
							id: `${n.id}::aicall::${ci}`,
							bpmnId: null,
							isAiToolCall: true,
							parentId: n.id,
							parentBpmnId: n.bpmnId,
							aiRunName: ownRunName || slot.runName || null,
							toolBpmnId: call.tool_name,
							name: taskLabels.value[call.tool_name] || call.tool_name,
							callStatus: call.status,
							argsPreview: call.args_preview,
							resultPreview: call.result_preview,
							depth: n.depth || 0,
							stateLabel: call.status === "Error" ? "Error" : "Completed",
							// The dedicated run's own start time when one exists, else the parent's.
							timestamp: (ownRun.startedAt || slot.startedAt) ? new Date(ownRun.startedAt || slot.startedAt) : (n.timestamp || null),
							// A tool call has no workflow `data` — show what it carried instead.
							data: { arguments: call.args_preview || undefined, result: call.result_preview || undefined },
						})
					})
				}
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

// bpmnId → human label for every task spec in the diagram (top level and
// subprocess internals alike), so tool-call chips in the inspector can show
// shape labels instead of raw IDs like Activity_0q9helm. Specs without a
// label are omitted — consumers fall back to the ID.
const taskLabels = computed(() => {
	if (!details.value?.workflow_state) return {}
	try {
		const wfState = typeof details.value.workflow_state === "string"
			? JSON.parse(details.value.workflow_state)
			: details.value.workflow_state
		const labels = {}
		const collect = (taskSpecs) => {
			for (const [specName, specData] of Object.entries(taskSpecs || {})) {
				const label = specData.bpmn_name || specData.description
				if (label) labels[specName] = label
			}
		}
		collect(wfState.spec?.task_specs)
		for (const sub of Object.values(wfState.subprocess_specs || {})) collect(sub.task_specs)
		return labels
	} catch {
		return {}
	}
})

// ── Selected node ──

const selectedNode = computed(() => {
	if (selectedNodeId.value) return taskList.value.find((n) => n.id === selectedNodeId.value) || null
	if (selectedBpmnId.value) {
		const direct = taskList.value.find((n) => n.bpmnId === selectedBpmnId.value)
		if (direct) return direct
		// A tool-leaf shape has no SpiffWorkflow task-state entry — fall back to its synthetic row.
		const toolCallRows = taskList.value.filter((n) => n.toolBpmnId === selectedBpmnId.value)
		return toolCallRows.length ? toolCallRows[toolCallRows.length - 1] : null
	}
	return null
})



// ── AI Agent tool calls (WI-001426) ──
// Tool calls made by an AI Agent Task run inside the LLM loop, not as engine
// tasks — fetch them from the observability records (AI Agent Run → Step →
// Tool Call) so the history and diagram can show what the agent did.

// bpmnId → [ [calls of run 1], [calls of run 2], ... ] in run start order,
// one entry per run even when a run made no tool calls — the flattener zips
// this list to the agent task's visits, so slots must line up 1:1.
const aiCallRunsByBpmnId = ref({})
const aiRunTick = ref(0)

async function loadAiToolCalls() {
	try {
		// A Call Activity runs the called process as a SUBWORKFLOW of its caller,
		// so an agent task inside the called process records its run against the
		// CALLER's instance. Its bpmn_id is a shape of the called diagram, which
		// means that run is currently invisible on both pages: absent from this
		// one, and not a shape on the caller's. Look at the caller too when this
		// row is a called process, and let the shape filter below decide what
		// actually belongs here.
		const instanceScope = [instanceId.value]
		if (details.value?.parent_instance) instanceScope.push(details.value.parent_instance)
		const runs = await frappeRequest({
			url: "/api/method/frappe.client.get_list",
			params: {
				doctype: "AI Agent Run",
				fields: JSON.stringify(["name", "bpmn_id", "started_at"]),
				filters: JSON.stringify([["instance", "in", instanceScope]]),
				order_by: "started_at asc",
				limit_page_length: 0,
			},
		})
		if (!Array.isArray(runs) || !runs.length) { aiCallRunsByBpmnId.value = {}; return }

		const runByName = Object.fromEntries(runs.map((r) => [r.name, r.bpmn_id]))
		const steps = await frappeRequest({
			url: "/api/method/frappe.client.get_list",
			params: {
				doctype: "AI Agent Step",
				fields: JSON.stringify(["name", "run", "step_index"]),
				filters: JSON.stringify([["run", "in", Object.keys(runByName)]]),
				order_by: "step_index asc",
				limit_page_length: 0,
			},
		})
		if (!Array.isArray(steps) || !steps.length) { aiCallRunsByBpmnId.value = {}; return }

		const stepOrder = Object.fromEntries(steps.map((s, i) => [s.name, i]))
		const stepRun = Object.fromEntries(steps.map((s) => [s.name, s.run]))
		const calls = await frappeRequest({
			url: "/api/method/frappe.client.get_list",
			params: {
				doctype: "AI Agent Tool Call",
				fields: JSON.stringify(["parent", "tool_name", "tool_source", "status", "tool_args", "tool_result", "idx"]),
				filters: JSON.stringify([["parent", "in", steps.map((s) => s.name)]]),
				parent: "AI Agent Step",
				order_by: "idx asc",
				limit_page_length: 0,
			},
		})

		const preview = (v) => {
			if (v == null || v === "") return ""
			const s = typeof v === "string" ? v : JSON.stringify(v)
			return s.length > 160 ? s.slice(0, 160) + "…" : s
		}
		const byRun = {}
		;(Array.isArray(calls) ? calls : [])
			.filter((c) => c.tool_source === "diagram_task")
			.sort((a, b) => (stepOrder[a.parent] - stepOrder[b.parent]) || (a.idx - b.idx))
			.forEach((c) => {
				const runName = stepRun[c.parent]
				if (!runName) return
				;(byRun[runName] = byRun[runName] || []).push({
					tool_name: c.tool_name,
					status: c.status,
					args_preview: preview(c.tool_args),
					result_preview: preview(c.tool_result),
				})
			})
		// One slot per run in start order — including empty slots for runs
		// without tool calls — so run N always pairs with task visit N. Each
		// slot carries its run name so the flattener can stamp the visit's own
		// AI Agent Run onto the history row (the inspector fetches THAT run,
		// not "latest run for the shape").
		const grouped = {}
		runs.forEach((r) => {
			if (!r.bpmn_id) return
			;(grouped[r.bpmn_id] = grouped[r.bpmn_id] || []).push({
				runName: r.name,
				startedAt: r.started_at || null,
				calls: byRun[r.name] || [],
			})
		})
		aiCallRunsByBpmnId.value = grouped
	} catch (e) {
		console.warn("Failed to load AI tool calls:", e)
		aiCallRunsByBpmnId.value = {}
	}
}

// Diagram highlight: toolbox shapes the agent actually called (WI-001426).
// bpmnId → "Success" | "Error" (an Error anywhere wins for that shape).
// Shape ids present in the diagram currently on screen. Used to keep a caller's
// tool calls off a called process's page and vice versa. Derived from the XML
// rather than checked at fetch time because the XML and the tool calls load
// independently — a fetch-time check would race and silently drop everything
// whenever the calls came back first.
const diagramShapeIds = computed(() => {
	const ids = new Set()
	const text = bpmnXml.value || ""
	const re = /\sid="([^"]+)"/g
	let m
	while ((m = re.exec(text)) !== null) ids.add(m[1])
	return ids
})

const aiCalledTools = computed(() => {
	// {tool_name: {status, count}} — status is "Error" if ANY call errored;
	// count is the number of times the agent called this tool (drives the
	// ×N badge on the tool shape).
	//
	// A tool's name IS its shape id, so anything not in this diagram belongs to
	// another one — the caller's own toolbox, when this row is a called process.
	// Without the check a caller's tool counts would leak onto this page and land
	// on any shape whose id happened to match.
	const shapes = diagramShapeIds.value
	const map = {}
	for (const runs of Object.values(aiCallRunsByBpmnId.value)) {
		for (const slot of runs) {
			for (const c of slot.calls || []) {
				if (shapes.size && !shapes.has(c.tool_name)) continue
				const entry = map[c.tool_name] || (map[c.tool_name] = { status: c.status, count: 0 })
				entry.count += 1
				if (c.status === "Error") entry.status = "Error"
			}
		}
	}
	return map
})

// ── Waiting for AI execution (WI-001499) ──
// AI tasks reached by an engine pass are parked (STARTED) while ONLY their
// LLM work runs as a bpmn_ai_agent job. waiting_for_ai flags the instance;
// get_parked_ai_tasks names the parked units for the banner, the diagram
// highlight, and the manual retry (WI-001497) after exhausted retries.

const parkedAiTasks = ref([])
const retryingAi = ref(false)

const waitingForAi = computed(() => Boolean(details.value?.waiting_for_ai))

const parkedAiLabels = computed(() =>
	parkedAiTasks.value.map((u) => u.label || u.bpmn_id).join(", ")
)

const waitingAiMap = computed(() => {
	const map = {}
	if (waitingForAi.value || details.value?.status === "Errored") {
		for (const u of parkedAiTasks.value) {
			map[u.bpmn_id] = details.value?.status === "Errored" ? "Error" : "Waiting"
		}
	}
	// Durable HITL: a suspended agent gets its own marker — it is waiting
	// for a person, not for an AI job.
	for (const s of suspendedAiTasks.value) {
		map[s.bpmn_id] = "Human"
	}
	return map
})

// ── Suspended agents waiting for a human (Durable AI Agent HITL) ──
const suspendedAiTasks = ref([])
const waitingForHuman = computed(() => details.value?.waiting_for_human || "")

async function loadSuspendedAiTasks() {
	if (!waitingForHuman.value) {
		suspendedAiTasks.value = []
		return
	}
	try {
		const res = await frappeRequest({
			url: "/api/method/one_bpmn.api.instance_api.get_suspended_ai_tasks",
			params: { instance_name: instanceId.value },
		})
		suspendedAiTasks.value = Array.isArray(res) ? res : []
	} catch (e) {
		console.warn("Failed to load suspended AI tasks:", e)
		suspendedAiTasks.value = []
	}
}

async function loadParkedAiTasks() {
	if (!waitingForAi.value && details.value?.status !== "Errored") {
		parkedAiTasks.value = []
		return
	}
	try {
		const res = await frappeRequest({
			url: "/api/method/one_bpmn.api.instance_api.get_parked_ai_tasks",
			params: { instance_name: instanceId.value },
		})
		parkedAiTasks.value = Array.isArray(res) ? res : []
	} catch (e) {
		console.warn("Failed to load parked AI tasks:", e)
		parkedAiTasks.value = []
	}
}

async function retryAiTasks() {
	if (retryingAi.value || !parkedAiTasks.value.length) return
	retryingAi.value = true
	try {
		for (const u of parkedAiTasks.value) {
			await frappeRequest({
				url: "/api/method/one_bpmn.api.instance_api.retry_ai_task",
				method: "POST",
				params: { instance_name: instanceId.value, task_id: u.task_id, kind: u.kind },
			})
		}
		await loadDetails()
	} catch (e) {
		console.error("AI retry failed:", e)
		taskError.value = "AI retry could not be queued. Please try again."
	} finally {
		retryingAi.value = false
	}
}

// ── Selection handlers ──

function onHistorySelect(node) {
	if (node.isAiToolCall) {
		// An AI call row selects its agent task and opens the AI Run tab —
		// the call's full trace lives there, not in engine task data.
		selectedNodeId.value = node.parentId
		selectedBpmnId.value = node.parentBpmnId
		aiRunTick.value++
		return
	}
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
		loadAiToolCalls()
		loadParkedAiTasks()
		loadSuspendedAiTasks()
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
		const data = res
		if (data?.xml_content) {
			// Assign the XML verbatim. bpmn-js parses XML entities itself, so we
			// must NOT HTML-decode it first — doing so turns required escaping like
			// `&lt;` in a condition (e.g. `gen_attempts &lt; 3`) into a literal `<`,
			// which corrupts the XML ("illegal first char nodeName"). The editor
			// (BpmnEditor.vue loadXML) imports the raw XML for the same reason.
			bpmnXml.value = data.xml_content
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
			await frappeRequest({
				url: "/api/method/one_bpmn.api.instance_api.complete_task",
				method: "POST",
				params: {
					instance_name: instanceId.value,
					task_id: task.task_id,
					data: actionName ? JSON.stringify({ action: actionName }) : "{}",
				},
			})

			// Success — refresh data
			logs.value = []
			limitStart.value = 0
			hasMoreLogs.value = true
			await loadDetails()
			await loadLogs()
		} catch (err) {
			// Extract the human-readable message from the frappeRequest error
			let errMsg = "Failed to complete task. Please try again."
			try {
				if (err.messages && err.messages.length) {
					errMsg = err.messages[0]
				} else if (err.exc) {
					const m = err.exc.match(/(?:PermissionError|ValidationError):\s*(.+)/)
					if (m) errMsg = m[1].trim()
				} else if (err.message) {
					errMsg = err.message
				}
			} catch (_) { /* keep default */ }
			taskError.value = errMsg
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

// ── Manual refresh (WI: Refresh button) ──
// Re-pull the instance, its logs and AI tool calls on demand so the user can
// see the latest state without waiting for a realtime event or reloading the
// page. Guarded so overlapping clicks don't stack requests.
async function refresh() {
	if (refreshing.value) return
	refreshing.value = true
	try {
		await loadDetails()
		logs.value = []
		limitStart.value = 0
		hasMoreLogs.value = true
		await loadLogs()
	} finally {
		refreshing.value = false
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

// ── Background engine tracking ──
// The engine (task dispatch + AI decisions) runs in a background job after
// document triggers and user actions. While it does, engine_in_progress is
// set (or the instance is still Queued) — show progress and poll as a
// fallback in case the realtime completion event is missed.
const engineBusy = computed(
	() => details.value?.status === "Queued" || Boolean(details.value?.engine_in_progress)
)

// WI-001499: also poll while waiting on an AI job — realtime is primary,
// this is the fallback if the job's completion event is missed. NOTE:
// waitingForAi deliberately does NOT feed engineBusy — the gate is clear
// while waiting, so pending human actions stay enabled (WI-001498).
const enginePolling = computed(() => engineBusy.value || waitingForAi.value)

let enginePollTimer = null
watch(enginePolling, (busy) => {
	if (busy && !enginePollTimer) {
		enginePollTimer = setInterval(async () => {
			await loadDetails()
			if (!enginePolling.value) {
				logs.value = []
				limitStart.value = 0
				hasMoreLogs.value = true
				await loadLogs()
			}
		}, 4000)
	} else if (!busy && enginePollTimer) {
		clearInterval(enginePollTimer)
		enginePollTimer = null
	}
})

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
	if (enginePollTimer) {
		clearInterval(enginePollTimer)
		enginePollTimer = null
	}
})
</script>
