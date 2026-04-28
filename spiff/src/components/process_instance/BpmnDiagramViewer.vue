<template>
	<div class="bg-white border-b flex flex-col relative" style="height: 60%; min-height: 250px;">
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

const props = defineProps({
	xml: { type: String, default: null },
	details: { type: Object, default: null },
	logs: { type: Array, default: () => [] },
	activeTasks: { type: Array, default: () => [] },
	selectedBpmnId: { type: String, default: null },
})

const emit = defineEmits(["element-select", "clear-selection"])

const canvasRef = ref(null)
const viewer = shallowRef(null)

// ── Viewer Lifecycle ──

async function initViewer() {
	if (!canvasRef.value || !props.xml) return
	if (!viewer.value) {
		viewer.value = new NavigatedViewer({
			container: canvasRef.value,
			width: "100%",
			height: "100%",
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
	} catch (err) {
		console.error("Error rendering BPMN:", err)
	}
}

onMounted(() => {
	if (canvasRef.value && props.xml) initViewer()
})

onUnmounted(() => {
	if (viewer.value) {
		viewer.value.destroy()
		viewer.value = null
	}
})

// ── Watchers ──

watch(() => props.xml, (val) => {
	if (val && canvasRef.value) initViewer()
})

watch([() => props.logs, () => props.activeTasks, () => props.xml], () => {
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

		const completedBpmnIds = new Set()
		const activeBpmnIds = new Set()
		const frequencyMap = {}

		// Parse workflow_state for task states
		if (props.details?.workflow_state) {
			try {
				const wfState = typeof props.details.workflow_state === "string"
					? JSON.parse(props.details.workflow_state)
					: props.details.workflow_state
				const tasks = wfState.tasks || {}
				for (const [, taskData] of Object.entries(tasks)) {
					const taskSpec = taskData.task_spec || ""
					if (!taskSpec || taskSpec === "Start" || taskSpec === "End" || taskSpec.endsWith(".EndJoin")) continue
					const state = taskData.state || 0
					if (state === 64) {
						completedBpmnIds.add(taskSpec)
						frequencyMap[taskSpec] = (frequencyMap[taskSpec] || 0) + 1
					} else if (state === 8 || state === 16 || state === 32) {
						activeBpmnIds.add(taskSpec)
					}
				}
			} catch (e) {
				// ignore parse errors
			}
		}

		// Supplement from logs
		props.logs
			.filter((l) => l.action === "Completed")
			.forEach((l) => {
				if (l.bpmn_id) completedBpmnIds.add(l.bpmn_id)
			})

		props.activeTasks.forEach((t) => {
			if (t.bpmn_id) activeBpmnIds.add(t.bpmn_id)
		})

		// Active tasks override completed
		activeBpmnIds.forEach((id) => completedBpmnIds.delete(id))

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

		// Active markers
		activeBpmnIds.forEach((bpmnId) => {
			try { canvas.addMarker(bpmnId, "highlight-active") } catch (e) {}
		})

		// Sequence flows, start events, and gateways
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
							const sourceDone = completedBpmnIds.has(sourceId) || element.source?.type === "bpmn:StartEvent"
							const targetReached = allReachedIds.has(targetId)
							if (targetReached || (sourceDone && element.target?.type?.includes("EndEvent"))) {
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

/* Cursor + overlays */
.bpmn-canvas-container .djs-overlay-container { pointer-events: none; }
.bpmn-canvas-container .djs-overlay { pointer-events: all; }
.bpmn-canvas-container .djs-element { cursor: pointer; }
.bpmn-canvas-container .djs-connection { cursor: pointer; }

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

/* Active pulse animation */
@keyframes active-pulse {
	0% { filter: drop-shadow(0 0 2px rgba(37,99,235,0.4)); }
	50% { filter: drop-shadow(0 0 8px rgba(37,99,235,0.8)); }
	100% { filter: drop-shadow(0 0 2px rgba(37,99,235,0.4)); }
}
</style>
