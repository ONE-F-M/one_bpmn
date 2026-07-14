<template>
	<div class="bg-white border-b flex flex-col relative" style="height: 60%; min-height: 250px; touch-action: none; overscroll-behavior: contain;">
		<!-- Zoom controls -->
		<div class="absolute top-3 right-4 z-20 flex items-center bg-white rounded shadow-sm border overflow-hidden text-gray-600">
			<button @click="zoomOut" class="p-1.5 hover:bg-gray-50 border-r" title="Zoom Out">
				<Icon icon="lucide:zoom-out" class="w-4 h-4" />
			</button>
			<button @click="resetZoom" class="p-1.5 hover:bg-gray-50 border-r" title="Reset">
				<Icon icon="lucide:search" class="w-4 h-4" />
			</button>
			<button @click="zoomIn" class="p-1.5 hover:bg-gray-50 border-r" title="Zoom In">
				<Icon icon="lucide:zoom-in" class="w-4 h-4" />
			</button>
			<button @click="fitViewport" class="p-1.5 hover:bg-blue-50 text-blue-600" title="Fit">
				<Icon icon="lucide:maximize" class="w-4 h-4" />
			</button>
		</div>

		<!-- Canvas -->
		<div class="relative w-full flex-1 bg-slate-50">
			<div v-show="xml" ref="canvasRef" class="absolute inset-0 z-0 bpmn-canvas-container"></div>
			<div v-if="!xml" class="absolute inset-0 z-10 flex flex-col items-center justify-center text-gray-400">
				<Icon icon="lucide:monitor-play" class="w-8 h-8 mb-2 opacity-50 animate-pulse" />
				<span class="font-medium">Rendering engine...</span>
			</div>
		</div>

		<!-- Legend -->
		<div class="px-5 py-1.5 border-t bg-white flex items-center justify-center gap-5 text-[10px] text-gray-500">
			<div class="flex items-center gap-1.5">
				<div class="w-2.5 h-2.5 rounded-sm bg-[#dcfce7] border border-[#16a34a]"></div>
				<span class="font-bold uppercase">Completed</span>
			</div>
			<div class="flex items-center gap-1.5">
				<div class="w-2.5 h-2.5 rounded-sm bg-[#dbeafe] border-2 border-[#2563eb] animate-pulse"></div>
				<span class="font-bold uppercase text-blue-700">Active</span>
			</div>
			<div class="flex items-center gap-1.5">
				<div class="w-2.5 h-2.5 rounded-sm bg-white border border-gray-400"></div>
				<span class="font-bold uppercase">Pending</span>
			</div>
			<div class="flex items-center gap-1 ml-2">
				<span class="font-bold uppercase text-gray-400 text-[9px]">Heat:</span>
				<div class="flex gap-0.5">
					<div class="w-2 h-2 rounded-sm bg-[#dcfce7] border border-[#16a34a]"></div>
					<div class="w-2 h-2 rounded-sm bg-[#fef9c3] border border-[#ca8a04]"></div>
					<div class="w-2 h-2 rounded-sm bg-[#fed7aa] border border-[#ea580c]"></div>
					<div class="w-2 h-2 rounded-sm bg-[#fecaca] border border-[#dc2626]"></div>
				</div>
			</div>
		</div>

		<!-- Hidden SVG marker for green arrows -->
		<svg style="position: absolute; width: 0; height: 0;" aria-hidden="true">
			<defs>
				<marker
					id="sequenceflow-arrow-green"
					viewBox="0 0 20 20"
					refX="11" refY="10"
					markerWidth="10" markerHeight="10"
					orient="auto"
				>
					<path d="M 1 5 L 11 10 L 1 15 Z" fill="#16a34a" stroke="#16a34a" />
				</marker>
			</defs>
		</svg>
	</div>
</template>

<script setup>
import { ref, shallowRef, watch, onMounted, onUnmounted } from "vue"
import { Icon } from "@iconify/vue"
import NavigatedViewer from "bpmn-js/lib/NavigatedViewer"
import "bpmn-js/dist/assets/diagram-js.css"
import "bpmn-js/dist/assets/bpmn-font/css/bpmn.css"

// Direct touch handler for mobile — bypasses bpmn-js-touch-interaction module
// which may fail to initialize on some devices due to (pointer: coarse) guard.
import { setupCanvasTouchHandler } from "@/utils/canvasTouchHandler"

// ── AI Agent Task renderer — replaces Service Task gear icon with sparkle ──
import aiAgentRendererModule from "@/bpmn/aiAgentRenderer"
import aiTaskSelectorRendererModule from "@/bpmn/aiTaskSelectorRenderer"

// ── Viewer-side moddle extension ──
// The BPMN XML produced by the editor uses custom spiffworkflow:* attributes
// (e.g. notifyAssigneeBody, emailBody).  Without registering the moddle
// extension, the viewer's XML parser treats unknown attributes containing
// angle brackets as malformed XML tags, causing "unparsable content" errors.
//
// This is a lightweight inline definition — we do NOT import the full
// bpmn-js-spiffworkflow module to avoid bloating the viewer bundle.
const viewerModdleExtension = {
	name: "spiffworkflow",
	uri: "http://spiffworkflow.org/bpmn/schema/1.0/core",
	prefix: "spiffworkflow",
	xml: { tagAlias: "lowerCase" },
	types: [
		{
			name: "UserTaskAssigneeExtension",
			extends: ["bpmn:UserTask"],
			properties: [
				{ name: "assigneeMode",         isAttr: true, type: "String" },
				{ name: "targetDoctype",         isAttr: true, type: "String" },
				{ name: "assigneeUser",          isAttr: true, type: "String" },
				{ name: "assigneeDocfield",      isAttr: true, type: "String" },
				{ name: "assigneeUsers",         isAttr: true, type: "String" },
				{ name: "roundRobinLastUser",    isAttr: true, type: "String" },
				{ name: "taskActions",           isAttr: true, type: "String" },
				{ name: "notifyAssignee",        isAttr: true, type: "String" },
				{ name: "notifyAssigneeBody",    isAttr: true, type: "String" },
				{ name: "notifyAssigneeSubject", isAttr: true, type: "String" },
				{ name: "notifyAssigneeTemplate", isAttr: true, type: "String" },
			],
		},
		{
			name: "ServiceTaskApplyWorkflowExtension",
			extends: ["bpmn:ServiceTask"],
			properties: [
				{ name: "serviceType",          isAttr: true, type: "String" },
				{ name: "serviceTargetDoctype", isAttr: true, type: "String" },
				{ name: "workflowState",        isAttr: true, type: "String" },
				{ name: "emailBody",            isAttr: true, type: "String" },
				{ name: "emailSubject",         isAttr: true, type: "String" },
				{ name: "emailTo",              isAttr: true, type: "String" },
				{ name: "emailAccount",         isAttr: true, type: "String" },
				{ name: "emailCc",              isAttr: true, type: "String" },
				{ name: "emailBcc",             isAttr: true, type: "String" },
				{ name: "gchatMessage",         isAttr: true, type: "String" },
				{ name: "pushTitle",            isAttr: true, type: "String" },
				{ name: "pushMessage",          isAttr: true, type: "String" },
				{ name: "onlyAllowEdit",        isAttr: true, type: "String" },
				{ name: "updateFieldDoctype",   isAttr: true, type: "String" },
				{ name: "updateFieldName",      isAttr: true, type: "String" },
				{ name: "updateFieldValue",     isAttr: true, type: "String" },
				{ name: "updateFieldRows",      isAttr: true, type: "String" },
				{ name: "emailDoctype",         isAttr: true, type: "String" },
				{ name: "emailToDocFields",     isAttr: true, type: "String" },
				{ name: "emailToRoles",         isAttr: true, type: "String" },
				{ name: "gchatType",            isAttr: true, type: "String" },
				{ name: "gchatEmail",           isAttr: true, type: "String" },
				{ name: "gchatSpaceId",         isAttr: true, type: "String" },
				{ name: "pushToUsers",          isAttr: true, type: "String" },
				{ name: "pushToDocFields",      isAttr: true, type: "String" },
				{ name: "pushToRoles",          isAttr: true, type: "String" },
				{ name: "serviceDocstatus",     isAttr: true, type: "String" },
			],
		},
		{
			name: "ScriptTaskServerScriptExtension",
			extends: ["bpmn:ScriptTask"],
			properties: [
				{ name: "serverScript", isAttr: true, type: "String" },
			],
		},
		{
			// WI-001360: lets the viewer read the AI Task Selector tag so the
			// wrench badge renders on selector-configured ad-hoc subprocesses.
			name: "AdhocAiTaskSelectorExtension",
			extends: ["bpmn:AdHocSubProcess"],
			properties: [
				{ name: "serviceType",    isAttr: true, type: "String" },
				{ name: "aiProvider",     isAttr: true, type: "String" },
				{ name: "aiModel",        isAttr: true, type: "String" },
				{ name: "aiSystemPrompt", isAttr: true, type: "String" },
				{ name: "aiUserPrompt",   isAttr: true, type: "String" },
				{ name: "aiToolSources",  isAttr: true, type: "String" },
			],
		},
	],
}

const props = defineProps({
	xml: { type: String, default: null },
	details: { type: Object, default: null },
	logs: { type: Array, default: () => [] },
	activeTasks: { type: Array, default: () => [] },
	selectedBpmnId: { type: String, default: null },
	// WI-001426: toolbox shapes the AI agent called as function-tools —
	// bpmnId → "Success" | "Error". These shapes never executed as flow,
	// so they get the same green treatment as engine-executed shapes.
	aiCalledTools: { type: Object, default: () => ({}) },
	// WI-001499: AI units parked "Waiting for AI execution" (or Errored
	// after retries) — bpmnId → "Waiting" | "Error". Pulsing blue outline.
	waitingAiTasks: { type: Object, default: () => ({}) },
})

const emit = defineEmits(["element-select", "clear-selection"])

const canvasRef = ref(null)
const viewer = shallowRef(null)
let touchCleanup = null

// ── Viewer Lifecycle ──

async function initViewer() {
	if (!canvasRef.value || !props.xml) return
	if (!viewer.value) {
		viewer.value = new NavigatedViewer({
			container: canvasRef.value,
			width: "100%",
			height: "100%",
			additionalModules: [
				aiAgentRendererModule,
				aiTaskSelectorRendererModule,
			],
			moddleExtensions: {
				spiffworkflow: viewerModdleExtension,
			},
		})
		viewer.value.get("eventBus").on("element.click", onElementClick)
		viewer.value.get("eventBus").on("canvas.click", () => emit("clear-selection"))
	}
	try {
		await viewer.value.importXML(props.xml)
		setTimeout(() => {
			try {
				viewer.value.get("canvas").zoom("fit-viewport", "auto")
				applyHighlights()
			} catch (e) {
				// ignore zoom errors
			}
		}, 100)

		// Setup direct touch handler for mobile pinch-to-zoom & finger pan
		// (only on touch-capable devices to avoid no-op listeners on desktop)
		const isTouchDevice = 'ontouchstart' in window || navigator.maxTouchPoints > 0
		if (!touchCleanup && canvasRef.value && isTouchDevice) {
			touchCleanup = setupCanvasTouchHandler(viewer.value, canvasRef.value)
		}
	} catch (err) {
		console.error("Error rendering BPMN:", err)
	}
}

onMounted(() => {
	if (canvasRef.value && props.xml) initViewer()
})

onUnmounted(() => {
	if (touchCleanup) {
		touchCleanup()
		touchCleanup = null
	}
	if (viewer.value) {
		viewer.value.destroy()
		viewer.value = null
	}
})

// ── Watchers ──

watch(() => props.xml, (val) => {
	if (val && canvasRef.value) initViewer()
})

watch([() => props.logs, () => props.activeTasks, () => props.xml, () => props.aiCalledTools, () => props.waitingAiTasks], () => {
	applyHighlights()
}, { deep: true })

watch(() => props.selectedBpmnId, (bpmnId) => {
	updateSelectionMarker(bpmnId)
})

// ── Zoom Controls ──

function zoomIn() {
	if (!viewer.value) return
	const canvas = viewer.value.get("canvas")
	canvas.zoom(canvas.zoom() * 1.2)
}

function zoomOut() {
	if (!viewer.value) return
	const canvas = viewer.value.get("canvas")
	canvas.zoom(canvas.zoom() / 1.2)
}

function resetZoom() {
	if (viewer.value) viewer.value.get("canvas").zoom(1)
}

function fitViewport() {
	if (viewer.value) viewer.value.get("canvas").zoom("fit-viewport", "auto")
}

// ── Selection Marker (single source of truth) ──

function updateSelectionMarker(bpmnId) {
	if (!viewer.value) return
	try {
		const canvas = viewer.value.get("canvas")
		viewer.value.get("elementRegistry").forEach((el) => {
			try { canvas.removeMarker(el.id, "highlight-selected") } catch (_) {}
		})
		if (bpmnId) {
			canvas.addMarker(bpmnId, "highlight-selected")
		}
	} catch (e) {
		// ignore
	}
}

// ── Element Click Handler ──

function onElementClick(e) {
	const elementId = e.element.id
	if (e.element.type === "bpmn:Process" || e.element.type === "bpmn:Collaboration") return
	emit("element-select", elementId)
}

// ── Highlights & Heatmap ──

function applyHighlights() {
	if (!viewer.value || !props.xml) return
	try {
		const canvas = viewer.value.get("canvas")
		const elementRegistry = viewer.value.get("elementRegistry")
		const overlays = viewer.value.get("overlays")
		overlays.remove({ type: "heatmap-badge" })
	overlays.remove({ type: "ai-badge" })
	overlays.remove({ type: "ai-call-badge" })
	overlays.remove({ type: "token-badge" })

		// Clear stale highlight markers before re-applying
		const staticHighlightMarkers = new Set(["highlight-done", "highlight-active", "highlight-ai-called", "highlight-ai-error", "highlight-ai-waiting", "highlight-ai-human"])
		const dynamicHighlightPrefixes = ["heatmap-", "highlight-flow-"]
		for (const element of elementRegistry.getAll()) {
			const gfx = elementRegistry.getGraphics(element)
			if (!gfx?.classList) continue
			for (const marker of Array.from(gfx.classList)) {
				if (
					staticHighlightMarkers.has(marker) ||
					dynamicHighlightPrefixes.some(prefix => marker.startsWith(prefix))
				) {
					canvas.removeMarker(element, marker)
				}
			}
		}

		const completedBpmnIds = new Set()
		const activeBpmnIds = new Set()   // READY (16) or STARTED (32) — truly executing
		const waitingBpmnIds = new Set()  // WAITING (8) — passively listening (boundary events, timers)
		const containerSpecs = new Set()  // Sub-Process / Ad-hoc parents — highlighted, but no token dot
		const frequencyMap = {}

		// Parse workflow_state for task states.
		// Inner tasks of Sub-Processes / Ad-hoc Subprocesses are serialized
		// under workflow_state.subprocesses[<parent task id>].tasks — walk
		// those too so subtasks light up and carry the token.
		if (props.details?.workflow_state) {
			try {
				const wfState = typeof props.details.workflow_state === "string"
					? JSON.parse(props.details.workflow_state)
					: props.details.workflow_state
				const subprocesses = wfState.subprocesses || {}

				const classify = (tasksDict) => {
					for (const [taskId, taskData] of Object.entries(tasksDict || {})) {
						const taskSpec = taskData.task_spec || ""
						if (subprocesses[taskId]) containerSpecs.add(taskSpec)
						if (!taskSpec || taskSpec === "Start" || taskSpec === "End" || taskSpec.endsWith(".EndJoin")) continue
						const state = taskData.state || 0
						if (state === 64) {
							completedBpmnIds.add(taskSpec)
							frequencyMap[taskSpec] = (frequencyMap[taskSpec] || 0) + 1
						} else if (state === 8) {
							// WAITING — boundary events/timers that are listening but
							// haven't fired. Show as active on the element but do NOT
							// include in flow-coloring (their outgoing paths are untouched).
							waitingBpmnIds.add(taskSpec)
						} else if (state === 16 || state === 32) {
							activeBpmnIds.add(taskSpec)
						}
					}
				}

				classify(wfState.tasks)
				for (const sub of Object.values(subprocesses)) {
					classify(sub.tasks)
				}
			} catch (e) {
				// ignore parse errors
			}
		}

		// Active tasks override completed
		activeBpmnIds.forEach((id) => completedBpmnIds.delete(id))
		waitingBpmnIds.forEach((id) => completedBpmnIds.delete(id))

		const maxFreq = Math.max(1, ...Object.values(frequencyMap))

		// Apply markers to completed tasks
		completedBpmnIds.forEach((bpmnId) => {
			try {
				const count = frequencyMap[bpmnId] || 1
				if (count > 1 && maxFreq > 1) {
					const ratio = (count - 1) / (maxFreq - 1)
					const level = Math.min(4, Math.max(1, Math.ceil(ratio * 4)))
					canvas.addMarker(bpmnId, `heatmap-${level}`)
					const badge = document.createElement("div")
					badge.className = `heatmap-badge ${level >= 4 ? "hot" : level >= 3 ? "warm" : ""}`
					badge.textContent = `×${count}`
					overlays.add(bpmnId, "heatmap-badge", { position: { top: -10, right: -10 }, html: badge })
				} else {
					canvas.addMarker(bpmnId, "highlight-done")
				}
			} catch (e) {
				// ignore
			}
		})

		// Active markers (READY / STARTED) + a token dot on the element the
		// process is actually sitting on. Container parents (Sub-Process /
		// Ad-hoc) are STARTED for as long as any inner task runs — they get
		// the active outline but the token belongs to the inner task.
		activeBpmnIds.forEach((bpmnId) => {
			try {
				canvas.addMarker(bpmnId, "highlight-active")
				if (!containerSpecs.has(bpmnId)) {
					const token = document.createElement("div")
					token.className = "bpmn-token"
					token.title = "Process token — the active task"
					overlays.add(bpmnId, "token-badge", { position: { bottom: 6, left: -7 }, html: token })
				}
			} catch (e) {}
		})
		// Waiting markers (boundary events / timers listening — show as active on element only)
		waitingBpmnIds.forEach((bpmnId) => {
			try { canvas.addMarker(bpmnId, "highlight-active") } catch (e) {}
		})

		// AI-called toolbox shapes (WI-001426): the agent invoked these as
		// function-tools inside its LLM loop — styled with the same green as
		// engine-executed shapes (errors get the error treatment) so AI and
		// engine runs read identically on the diagram.
		// info is {status, count} (legacy string = status only). Tools called
		// more than once get a ×N badge — same convention as the token
		// heatmap, but counting LLM tool calls, not token traversals.
		const aiToolboxIds = new Set()
		for (const [bpmnId, info] of Object.entries(props.aiCalledTools || {})) {
			try {
				const status = typeof info === "string" ? info : info?.status
				const count = (typeof info === "object" && info?.count) || 0
				canvas.addMarker(bpmnId, status === "Error" ? "highlight-ai-error" : "highlight-ai-called")
				if (count > 1) {
					const badge = document.createElement("div")
					badge.className = "ai-call-badge"
					badge.textContent = `×${count}`
					badge.title = `The agent called this tool ${count} times`
					overlays.add(bpmnId, "ai-call-badge", { position: { top: -10, right: -10 }, html: badge })
				}
				// The container holding this tool is an agent's toolbox — its
				// valve edges get the same executed-flow colouring.
				const parent = elementRegistry.get(bpmnId)?.parent
				if (parent?.type === "bpmn:AdHocSubProcess") aiToolboxIds.add(parent.id)
			} catch (e) {}
		}

		// Edges touching an AI-used toolbox: coloured like every other
		// executed flow, so AI-driven and engine-driven execution share one
		// visual language on the instance diagram.
		if (aiToolboxIds.size && elementRegistry) {
			elementRegistry
				.filter(
					(e) =>
						e.type === "bpmn:SequenceFlow" &&
						(aiToolboxIds.has(e.source?.id) || aiToolboxIds.has(e.target?.id)),
				)
				.forEach((element) => {
					try {
						canvas.addMarker(element.id, "highlight-flow-ai")
					} catch (e) {}
				})
		}

		// Parked AI units (WI-001499): waiting for their background AI job —
		// pulsing blue; an exhausted-retries failure gets the error look.
		// A suspended agent (Durable HITL, status "Human") is waiting for a
		// PERSON — distinct amber treatment.
		for (const [bpmnId, status] of Object.entries(props.waitingAiTasks || {})) {
			try {
				canvas.addMarker(
					bpmnId,
					status === "Error"
						? "highlight-ai-error"
						: status === "Human"
							? "highlight-ai-human"
							: "highlight-ai-waiting",
				)
			} catch (e) {}
		}

		// Sequence flows, start events, and gateways
		// NOTE: waitingBpmnIds are deliberately excluded — a WAITING boundary
		// event is passively listening and has not traversed its outgoing flow.
		const allReachedIds = new Set([...completedBpmnIds, ...activeBpmnIds])
		if (elementRegistry) {
			elementRegistry
				.filter((e) => e.type === "bpmn:SequenceFlow" || e.type === "bpmn:StartEvent")
				.forEach((element) => {
					try {
						if (element.type === "bpmn:StartEvent") {
							canvas.addMarker(element.id, "highlight-done")
						} else {
							const sourceId = element.source?.id
							const targetId = element.target?.id
							const sourceReached = allReachedIds.has(sourceId) || element.source?.type === "bpmn:StartEvent"
							const targetReached = allReachedIds.has(targetId)
							// Color a flow only when BOTH source and target were reached,
							// preventing false-positive coloring of untouched merge-gateway inflows.
							if ((sourceReached && targetReached) || (sourceReached && element.target?.type?.includes("EndEvent"))) {
								const srcFreq = frequencyMap[sourceId] || 0
								const tgtFreq = frequencyMap[targetId] || 0
								canvas.addMarker(element.id, srcFreq > 1 && tgtFreq > 1 ? "highlight-flow-hot" : "highlight-flow-done")
							}
						}
					} catch (e) {}
				})

			elementRegistry
				.filter((e) => e.type?.includes("Gateway"))
				.forEach((gw) => {
					try {
						const freq = frequencyMap[gw.id] || 0
						if (completedBpmnIds.has(gw.id)) {
							if (freq > 1 && maxFreq > 1) {
								const ratio = (freq - 1) / (maxFreq - 1)
								const level = Math.min(4, Math.max(1, Math.ceil(ratio * 4)))
								canvas.addMarker(gw.id, `heatmap-${level}`)
								const badge = document.createElement("div")
								badge.className = `heatmap-badge ${level >= 4 ? "hot" : level >= 3 ? "warm" : ""}`
								badge.textContent = `×${freq}`
								overlays.add(gw.id, "heatmap-badge", { position: { top: -10, right: -10 }, html: badge })
							} else {
								canvas.addMarker(gw.id, "highlight-done")
							}
						} else if (activeBpmnIds.has(gw.id)) {
							canvas.addMarker(gw.id, "highlight-active")
						}
					} catch (e) {}
				})
		}

		// ── AI Agent Task overlay badges (observability) ───────────
		if (props.details?.workflow_state) {
			try {
				const wfState = typeof props.details.workflow_state === "string"
					? JSON.parse(props.details.workflow_state)
					: props.details.workflow_state
				// serviceType lives in the compiled spec (service_task_extensions),
				// keyed by BPMN element id — not on the runtime task objects.
				let svcExt = {}
				try {
					const spec = typeof props.details.serialized_spec === "string"
						? JSON.parse(props.details.serialized_spec)
						: props.details.serialized_spec
					svcExt = spec?.service_task_extensions || {}
				} catch (e) { /* ignore */ }
				const tasks = wfState.tasks || {}
				// Clear any previous AI badge overlays before re-applying
				try { overlays.remove({ type: "ai-badge" }) } catch { /* no existing overlays */ }
				const subprocesses = wfState.subprocesses || {}
				for (const [taskId, td] of Object.entries(tasks)) {
					const taskSpec = td.task_spec || ""
					if (!taskSpec) continue
					const serviceType = (svcExt[taskSpec] || {}).serviceType
					if (serviceType !== "ai_agent" && serviceType !== "ai_task_selector") continue

					const state = td.state || 0
					// Selector error keys live in the ad-hoc SUBPROCESS data,
					// keyed by the parent task's id — check both places.
					const hasError =
						td.data?.[`${taskSpec}_error_code`] ||
						subprocesses[taskId]?.data?.[`${taskSpec}_error_code`]
					const isCompleted = state === 64
					const kind = serviceType === "ai_task_selector" ? "AI Task Selector" : "AI Agent Task"

					if (isCompleted || hasError) {
						const badge = document.createElement("div")
						badge.className = `ai-badge ${hasError ? "ai-error" : "ai-success"}`
						badge.textContent = hasError ? "!" : "AI"
						badge.title = hasError ? `${kind} failed` : `${kind} completed`
						overlays.add(taskSpec, "ai-badge", { position: { top: -10, left: -10 }, html: badge })
					}
				}
			} catch (e) {
				// ignore AI badge errors
			}
		}
	} catch (err) {
		console.warn("Could not apply highlights:", err)
	}
}
</script>

<style>
/* BPMN element markers */
.highlight-done:not(.djs-connection) .djs-visual > :nth-child(1) {
	stroke: #16a34a !important; fill: #dcfce7 !important; stroke-width: 2px !important;
}
.highlight-active:not(.djs-connection) .djs-visual > :nth-child(1) {
	stroke: #2563eb !important; fill: #dbeafe !important; stroke-width: 2px !important;
}
/* WI-001426: toolbox shapes called by the AI agent — same green as engine-
   executed shapes so AI and engine runs read identically on the diagram. */
.highlight-ai-called:not(.djs-connection) .djs-visual > :nth-child(1) {
	stroke: #16a34a !important; fill: #dcfce7 !important; stroke-width: 2px !important;
}
.highlight-ai-error:not(.djs-connection) .djs-visual > :nth-child(1) {
	stroke: #dc2626 !important; fill: #fee2e2 !important; stroke-width: 2px !important;
}
.highlight-ai-waiting:not(.djs-connection) .djs-visual > :nth-child(1) {
	stroke: #2563eb !important; fill: #dbeafe !important; stroke-width: 2.5px !important;
	animation: ai-waiting-pulse 1.6s ease-in-out infinite;
}
@keyframes ai-waiting-pulse {
	0%, 100% { stroke-opacity: 1; }
	50% { stroke-opacity: 0.35; }
}
/* Durable HITL: agent suspended, waiting for a person — amber, pulsing */
.highlight-ai-human:not(.djs-connection) .djs-visual > :nth-child(1) {
	stroke: #d97706 !important; fill: #fef3c7 !important; stroke-width: 2.5px !important;
	stroke-dasharray: 6 3 !important;
	animation: ai-waiting-pulse 1.6s ease-in-out infinite;
}
/* Edges of an agent's toolbox whose tools were AI-called: same green as
   engine-traversed flows — AI and engine runs use one consistent colour. */
.highlight-flow-ai.djs-connection .djs-visual > path {
	stroke: #16a34a !important; stroke-width: 2px !important;
	marker-end: url(#sequenceflow-arrow-green) !important;
}
.highlight-flow-done.djs-connection .djs-visual > path {
	stroke: #16a34a !important; stroke-width: 2px !important;
	marker-end: url(#sequenceflow-arrow-green) !important;
}
.highlight-flow-hot.djs-connection .djs-visual > path {
	stroke: #ea580c !important; stroke-width: 3px !important;
	marker-end: url(#sequenceflow-arrow-green) !important;
}

/* Heatmap levels */
.heatmap-1:not(.djs-connection) .djs-visual > :nth-child(1) { fill: #dcfce7 !important; stroke: #16a34a !important; stroke-width: 2px !important; }
.heatmap-2:not(.djs-connection) .djs-visual > :nth-child(1) { fill: #fef9c3 !important; stroke: #ca8a04 !important; stroke-width: 2px !important; }
.heatmap-3:not(.djs-connection) .djs-visual > :nth-child(1) { fill: #fed7aa !important; stroke: #ea580c !important; stroke-width: 2px !important; }
.heatmap-4:not(.djs-connection) .djs-visual > :nth-child(1) { fill: #fecaca !important; stroke: #dc2626 !important; stroke-width: 2.5px !important; }

/* Selection highlight */
.highlight-selected:not(.djs-connection) .djs-visual > :nth-child(1) {
	stroke: #4b5563 !important; stroke-width: 3px !important; fill: rgba(107, 114, 128, 0.12) !important;
}
.highlight-selected.djs-connection .djs-visual > :nth-child(1) {
	stroke: #4b5563 !important; stroke-width: 3px !important;
}

/* AI Agent badge */
.ai-badge {
	width: 16px;
	height: 16px;
	border-radius: 50%;
	display: flex;
	align-items: center;
	justify-content: center;
	font-size: 8px;
	font-weight: 700;
	font-family: monospace;
	color: #fff;
	cursor: default;
	box-shadow: 0 1px 3px rgba(0,0,0,0.15);
	z-index: 100;
}
.ai-badge.ai-success {
	background: #16a34a;
}
.ai-badge.ai-error {
	background: #DC2626;
}

/* Cursor + overlays */
.bpmn-canvas-container .djs-overlay-container { pointer-events: none; }
.bpmn-canvas-container .djs-overlay { pointer-events: all; }
.bpmn-canvas-container .djs-element { cursor: pointer; }
.bpmn-canvas-container .djs-connection { cursor: pointer; }

/* Prevent browser zoom/scroll on the canvas — let our touch handler manage it */
.bpmn-canvas-container {
	touch-action: none;
	-webkit-user-select: none;
	user-select: none;
	overscroll-behavior: contain;
}

/* Ensure parent wrapper doesn't intercept touch gestures meant for the canvas */
.bpmn-canvas-container * {
	touch-action: none;
}

/* Heatmap badges */
.heatmap-badge {
	min-width: 20px; height: 20px; line-height: 20px; text-align: center;
	font-size: 10px; font-weight: 700; color: #fff; background: #6366f1;
	border-radius: 10px; padding: 0 5px;
	box-shadow: 0 1px 3px rgba(0,0,0,0.3);
	font-family: ui-monospace, monospace; pointer-events: none;
}
.heatmap-badge.hot { background: #dc2626; }
.heatmap-badge.warm { background: #f59e0b; }

/* ×N tool-call count on AI-called toolbox shapes — same badge style as the
   token heatmap ×N so repeat counts read identically everywhere. */
.ai-call-badge {
	min-width: 20px; height: 20px; line-height: 20px; text-align: center;
	font-size: 10px; font-weight: 700; color: #fff; background: #6366f1;
	border-radius: 10px; padding: 0 5px;
	box-shadow: 0 1px 3px rgba(0,0,0,0.3);
	font-family: ui-monospace, monospace; pointer-events: none;
}

/* Active pulse animation */
@keyframes active-pulse {
	0% { filter: drop-shadow(0 0 2px rgba(37,99,235,0.4)); }
	50% { filter: drop-shadow(0 0 8px rgba(37,99,235,0.8)); }
	100% { filter: drop-shadow(0 0 2px rgba(37,99,235,0.4)); }
}

/* Process token — the classic BPMN dot marking the task the process is
   sitting on, including inner tasks of expanded (ad-hoc) subprocesses. */
.bpmn-token {
	width: 14px;
	height: 14px;
	border-radius: 50%;
	background: #2563eb;
	border: 2px solid #fff;
	box-shadow: 0 1px 4px rgba(0, 0, 0, 0.35);
	pointer-events: none;
	animation: token-pulse 1.6s ease-in-out infinite;
}
@keyframes token-pulse {
	0% { box-shadow: 0 1px 4px rgba(0, 0, 0, 0.35), 0 0 0 0 rgba(37, 99, 235, 0.45); }
	70% { box-shadow: 0 1px 4px rgba(0, 0, 0, 0.35), 0 0 0 8px rgba(37, 99, 235, 0); }
	100% { box-shadow: 0 1px 4px rgba(0, 0, 0, 0.35), 0 0 0 0 rgba(37, 99, 235, 0); }
}
</style>
