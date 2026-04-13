<template>
	<div class="h-full flex flex-col bg-gray-50">
		<header class="bg-white border-b px-6 py-4 flex items-center justify-between z-10 shrink-0 shadow-sm">
			<div class="flex items-center gap-4">
				<Button icon-left="arrow-left" variant="ghost" @click="router.push('/processa/instances')">Back</Button>
				<h1 class="text-xl font-semibold text-gray-900">Instance Details</h1>
			</div>
			<div v-if="details">
				<Badge :theme="getStatusTheme(details.status)" :label="details.status || 'Unknown'" size="lg" />
			</div>
		</header>
		<main class="flex-1 p-6 overflow-x-hidden overflow-y-auto relative">
			<div v-if="loading" class="flex justify-center flex-col items-center p-12 gap-4 h-full">
				<Icon icon="lucide:loader" class="w-8 h-8 text-gray-400 animate-spin" />
				<span class="text-gray-500">Loading details...</span>
			</div>
			
			<div v-else-if="details" class="max-w-[1400px] mx-auto space-y-6">
				
				<!-- TOP SECTION: Overview & Pending Actions Grid -->
				<div class="grid grid-cols-1 xl:grid-cols-3 gap-6">
					
					<!-- Instance Info Card (2/3 width) -->
					<div class="xl:col-span-2 bg-white rounded-lg shadow-sm border p-6 flex flex-col justify-center">
						<div class="flex flex-col md:flex-row md:items-center justify-between gap-4 mb-6">
							<div>
								<h2 class="text-xl font-bold text-gray-900 truncate tracking-tight" :title="details.name">{{ details.name }}</h2>
								<p class="text-sm text-gray-500 mt-1 flex items-center gap-2">
									<Icon icon="lucide:package" class="w-4 h-4" />
									{{ details.process_model }}
								</p>
							</div>
						</div>
						
						<div class="grid grid-cols-2 sm:grid-cols-3 gap-y-6 gap-x-4">
							<div>
								<div class="text-[11px] text-gray-400 font-bold uppercase tracking-[0.05em] mb-1">Context</div>
								<div class="text-[13px]">
									<a v-if="details.context_docname" :href="getContextDocumentLink()" class="font-semibold text-blue-600 hover:text-blue-700 hover:underline transition-colors flex items-center gap-1.5 bg-blue-50/50 px-2 py-1 rounded w-max">
										<Icon icon="lucide:file-text" class="w-3.5 h-3.5" />
										{{ details.context_docname }}
									</a>
									<span v-else class="text-gray-400 italic">None attached</span>
								</div>
							</div>
							<div>
								<div class="text-[11px] text-gray-400 font-bold uppercase tracking-[0.05em] mb-1">Initiated By</div>
								<div class="text-[13px] text-gray-800 font-medium truncate flex items-center gap-1.5" :title="details.initiated_by">
									<Icon icon="lucide:user-circle" class="w-4 h-4 text-gray-400" />
									{{ details.initiated_by || '-' }}
								</div>
							</div>
							<div>
								<div class="text-[11px] text-gray-400 font-bold uppercase tracking-[0.05em] mb-1">Started At</div>
								<div class="text-[13px] text-gray-800 font-medium font-mono flex items-center gap-1.5">
									<Icon icon="lucide:calendar-clock" class="w-4 h-4 text-gray-400" />
									{{ formatDateTime(details.started_at) }}
								</div>
							</div>
						</div>
					</div>

					<!-- Pending Action Items (1/3 width, Top Row) -->
					<div class="xl:col-span-1 border bg-white rounded-lg shadow-sm flex flex-col h-full max-h-[250px]">
						<div class="px-5 py-3 border-b bg-orange-50/30 flex items-center justify-between shrink-0">
							<h3 class="text-sm font-bold text-gray-800 flex items-center gap-2">
								<Icon icon="lucide:clock-4" class="w-4 h-4 text-orange-500" />
								Pending Actions
							</h3>
							<Badge v-if="activeTasks.length" theme="orange" :label="activeTasks.length.toString()" />
						</div>
						<div class="p-0 overflow-y-auto custom-scrollbar flex-1">
							<div v-if="activeTasks.length > 0" class="divide-y divide-gray-100">
								<div v-for="task in activeTasks" :key="task.task_id" class="p-4 hover:bg-gray-50 transition-colors group">
									<div class="flex justify-between items-start mb-1.5">
										<div class="font-semibold text-gray-800 text-[13px] group-hover:text-blue-600 transition-colors leading-tight">{{ task.task_name || task.task_id }}</div>
									</div>
									<div class="text-[11px] text-gray-500 mb-3 flex items-center gap-1 font-mono bg-gray-100 w-max px-1.5 py-0.5 rounded">
										Since <span class="font-semibold">{{ formatDateTime(task.started_at) }}</span>
									</div>
									
									<div v-if="task.assigned_user || task.assigned_role" class="bg-white border rounded p-1.5 px-2 text-[11px] text-gray-700 shadow-sm inline-flex items-center gap-3">
										<div v-if="task.assigned_user" class="flex items-center gap-1.5">
											<Icon icon="lucide:user" class="w-3 h-3 text-blue-500" />
											<span class="font-medium truncate max-w-[120px]">{{ task.assigned_user }}</span>
										</div>
										<div v-if="task.assigned_role" class="flex items-center gap-1.5">
											<Icon icon="lucide:users" class="w-3 h-3 text-purple-500" />
											<span class="font-medium truncate max-w-[120px]">{{ task.assigned_role }}</span>
										</div>
									</div>
									<div v-else class="text-[10px] text-orange-600 italic flex items-center gap-1 mt-1 bg-orange-50 px-1.5 py-0.5 rounded w-max border border-orange-100 font-bold tracking-wide">
										<Icon icon="lucide:alert-triangle" class="w-3 h-3" />
										UNASSIGNED
									</div>

									<!-- Decision Action Buttons -->
									<div v-if="getTaskActions(task).length" class="mt-3 flex flex-wrap gap-2">
										<button
											v-for="action in getTaskActions(task)"
											:key="action"
											@click="completeTask(task, action)"
											:disabled="completingTask === task.task_id"
											class="px-3 py-1.5 text-[11px] font-semibold rounded border transition-colors"
											:class="getActionButtonClass(action)"
										>
											<span v-if="completingTask === task.task_id && completingAction === action" class="flex items-center gap-1">
												<Icon icon="lucide:loader" class="w-3 h-3 animate-spin" /> Processing…
											</span>
											<span v-else>{{ action }}</span>
										</button>
									</div>
									<!-- Plain complete button when no actions configured -->
									<div v-else class="mt-3">
										<button
											@click="completeTask(task, null)"
											:disabled="completingTask === task.task_id"
											class="px-3 py-1.5 text-[11px] font-semibold rounded border bg-gray-100 hover:bg-gray-200 text-gray-700 border-gray-300 transition-colors disabled:opacity-50"
										>
											<span v-if="completingTask === task.task_id" class="flex items-center gap-1">
												<Icon icon="lucide:loader" class="w-3 h-3 animate-spin" /> Processing…
											</span>
											<span v-else class="flex items-center gap-1"><Icon icon="lucide:check" class="w-3 h-3" /> Complete</span>
										</button>
									</div>
								</div>
							</div>
							<div v-else class="h-full flex flex-col items-center justify-center text-center text-gray-400 text-sm p-6">
								<div class="w-10 h-10 rounded-full bg-green-50 flex items-center justify-center mb-3">
									<Icon icon="lucide:check" class="w-6 h-6 text-green-500" />
								</div>
								<span class="font-medium text-gray-500">No pending actions.</span>
								<span class="text-xs mt-1">The process is not blocked.</span>
							</div>
						</div>
					</div>
				</div>

				<!-- MAIN BODY: Right-Squished Variables & Diagram/History -->
				<div class="grid grid-cols-1 xl:grid-cols-4 gap-6 items-start">
					
					<!-- Left Stack: Diagram + History (3/4 width) -->
					<div class="xl:col-span-3 space-y-6 flex flex-col">
						
						<!-- Diagram Viewer Card -->
						<div class="bg-white rounded-lg shadow-sm border flex flex-col relative overflow-hidden">
							<div class="px-5 py-3 border-b bg-gray-50/80 flex items-center justify-between shrink-0 z-10">
								<h3 class="text-sm font-bold text-gray-800 flex items-center gap-2">
									<Icon icon="lucide:git-commit" class="w-4 h-4 text-purple-500" />
									Process Execution Flow
								</h3>
								
								<!-- Zoom Toolbar -->
								<div class="flex items-center bg-white rounded shadow-sm border overflow-hidden text-gray-600">
									<button @click="zoomOut" class="p-1.5 hover:bg-gray-50 border-r transition-colors" title="Zoom Out"><Icon icon="lucide:zoom-out" class="w-4 h-4" /></button>
									<button @click="resetZoom" class="p-1.5 hover:bg-gray-50 border-r transition-colors" title="Actual Size"><Icon icon="lucide:search" class="w-4 h-4" /></button>
									<button @click="zoomIn" class="p-1.5 hover:bg-gray-50 border-r transition-colors" title="Zoom In"><Icon icon="lucide:zoom-in" class="w-4 h-4" /></button>
									<button @click="fitViewport" class="p-1.5 hover:bg-blue-50 text-blue-600 transition-colors bg-gray-50/50" title="Fit to Screen"><Icon icon="lucide:maximize" class="w-4 h-4" /></button>
								</div>
							</div>
							
							<div class="relative w-full h-[450px] bg-slate-50">
								<div v-show="bpmnXml" ref="canvasRef" class="absolute inset-0 z-0 bpmn-canvas-container"></div>
								<div v-if="!bpmnXml" class="absolute inset-0 z-10 flex flex-col items-center justify-center text-gray-400">
									<Icon icon="lucide:monitor-play" class="w-8 h-8 mb-2 opacity-50 animate-pulse" />
									<span class="font-medium">Rendering engine...</span>
								</div>
							</div>
							
							<!-- Legend inside Diagram bottom border -->
							<div class="px-5 py-2 border-t bg-white shrink-0 flex items-center justify-center gap-5 text-[11px] text-gray-600 shadow-inner z-10 relative">
								<span class="font-bold mr-1 text-gray-400 uppercase tracking-widest text-[9px] flex items-center gap-1.5">
									<Icon icon="lucide:sliders-horizontal" class="w-3 h-3" />
									Legend:
								</span>
								<div class="flex items-center gap-1.5 px-2 py-0.5 rounded transition-colors group">
									<div class="w-3 h-3 justify-center items-center flex rounded-sm bg-[#dcfce7] border border-[#16a34a] overflow-hidden shadow-sm">
										<Icon icon="lucide:check" class="w-3 h-3 text-[#16a34a]" />
									</div>
									<span class="font-bold text-gray-700 tracking-wide uppercase">Completed</span>
								</div>
								<div class="w-px h-3 bg-gray-200"></div>
								<div class="flex items-center gap-1.5 px-2 py-0.5 rounded transition-colors group">
									<div class="w-3 h-3 rounded-sm bg-[#dbeafe] border-2 border-[#2563eb] animate-pulse shadow-sm"></div>
									<span class="font-bold text-blue-700 tracking-wide uppercase">Active</span>
								</div>
								<div class="w-px h-3 bg-gray-200"></div>
								<div class="flex items-center gap-1.5 px-2 py-0.5 rounded transition-colors group">
									<div class="w-3 h-3 rounded-sm bg-white border border-gray-400 shadow-sm"></div>
									<span class="font-bold text-gray-500 tracking-wide uppercase">Pending</span>
								</div>
							</div>
						</div>

						<!-- Ultra-Compact Execution History -->
						<div class="bg-white rounded-lg shadow-sm border overflow-hidden flex flex-col">
							<div class="px-5 py-3 border-b bg-emerald-50/40 shrink-0 flex items-center justify-between">
								<h3 class="text-sm font-bold text-gray-800 flex items-center gap-2">
									<Icon icon="lucide:history" class="w-4 h-4 text-emerald-600" />
									Execution Route
								</h3>
								<div class="text-[10px] font-mono text-gray-500 tracking-wide uppercase">
									Sequential Order
								</div>
							</div>
							
							<div class="max-h-[350px] overflow-y-auto custom-scrollbar bg-white">
								<div v-if="logs.length === 0" class="text-gray-500 text-sm p-6 text-center italic flex flex-col items-center justify-center gap-2">
									<Icon icon="lucide:info" class="w-5 h-5 opacity-40" />
									No timeline events recorded yet.
								</div>

								<table v-else class="w-full text-left whitespace-nowrap">
									<tbody class="divide-y divide-gray-100">
										<tr v-for="log in sortedLogs" :key="log.name" class="hover:bg-gray-50/50 transition-colors group">
											<td class="pl-5 pr-3 py-2.5 w-8">
												<Icon v-if="log.action === 'Completed'" icon="lucide:check-circle-2" class="w-4 h-4 text-green-500" />
												<Icon v-else-if="log.action === 'Started'" icon="lucide:play-circle" class="w-4 h-4 text-blue-500" />
												<Icon v-else-if="log.action === 'Errored'" icon="lucide:octagon-alert" class="w-4 h-4 text-red-500" />
												<Icon v-else icon="lucide:clock" class="w-4 h-4 text-gray-400" />
											</td>
											<td class="px-3 py-2.5 font-bold text-[13px] text-gray-800 max-w-[250px] truncate" :title="log.task_name || log.task_id">
												{{ log.task_name || log.task_id }}
											</td>
											<td class="px-3 py-2.5 w-24">
												<Badge :theme="getLogActionTheme(log.action)" :label="log.action" size="sm" class="font-medium tracking-tight" />
											</td>
											<td class="px-3 py-2.5 text-[11px] text-gray-500 font-mono w-40">
												{{ formatDateTime(log.timestamp) }}
											</td>
											<td class="pr-5 pl-3 py-2.5 text-[11px] text-gray-500 truncate max-w-[120px]">
												<span v-if="log.user" class="text-blue-700 bg-blue-50 px-1.5 py-0.5 rounded truncate inline-block w-full">
													{{ log.user }}
												</span>
											</td>
										</tr>
									</tbody>
								</table>

								<!-- Load More Logs -->
								<div v-if="hasMoreLogs" class="p-4 flex justify-center border-t border-gray-50 bg-gray-50/30">
									<Button @click="loadLogs" :loading="logsLoading" size="sm" variant="subtle" icon-left="refresh-cw" class="w-full max-w-xs shadow-sm">Load Older History</Button>
								</div>
							</div>
						</div>
					</div>
					
					<!-- Right Stack: Variables (1/4 width - "squished") -->
					<div class="xl:col-span-1">
						<div class="bg-white rounded-lg shadow-sm border flex flex-col sticky top-6 overflow-hidden max-h-[850px]">
							<div class="px-5 py-3 border-b bg-blue-50/40 shrink-0 flex items-center justify-between">
								<h3 class="text-sm font-bold text-gray-800 flex items-center gap-2">
									<Icon icon="lucide:braces" class="w-4 h-4 text-blue-500" />
									Process State Data
								</h3>
								<div class="text-[10px] font-mono text-gray-400 tracking-wide uppercase px-2 bg-gray-100 rounded">Variables</div>
							</div>
							<div class="overflow-y-auto flex-1 p-0 custom-scrollbar bg-gray-50/20">
								<div v-if="Object.keys(processVariables).length > 0" class="divide-y divide-gray-100/80">
									<div v-for="(value, key) in processVariables" :key="key" class="px-4 py-3 hover:bg-blue-50/30 transition-colors group">
										<div class="text-[11px] font-bold text-gray-400 uppercase tracking-wider mb-1 group-hover:text-blue-400 transition-colors break-all">
											{{ key }}
										</div>
										<div class="font-mono text-[12px] text-gray-800 break-words whitespace-pre-wrap bg-white border border-gray-100/50 p-2 rounded shadow-sm relative group-hover:border-blue-100 group-hover:shadow group-hover:bg-blue-50/10">
											{{ typeof value === 'object' ? JSON.stringify(value, null, 2) : value }}
										</div>
									</div>
								</div>
								<div v-else class="flex flex-col items-center justify-center p-10 text-center text-gray-400 h-64">
									<div class="w-12 h-12 rounded-full border-2 border-dashed border-gray-200 flex items-center justify-center mb-3">
										<Icon icon="lucide:ghost" class="w-6 h-6 text-gray-300" />
									</div>
									<span class="text-sm font-medium text-gray-500">No Custom Variables</span>
									<span class="text-[11px] mt-1 opacity-70">Engine state is currently empty or strictly structural.</span>
								</div>
							</div>
						</div>
					</div>
				</div>
			</div>
		</main>
	</div>
</template>

<script setup>
import { ref, shallowRef, onMounted, computed, watch, onUnmounted } from "vue"
import { useRoute, useRouter } from "vue-router"
import { frappeRequest, Badge, Button } from "frappe-ui"
import { dayjs } from "@/dayjs"
import { Icon } from "@iconify/vue"
import NavigatedViewer from "bpmn-js/lib/NavigatedViewer"
import "bpmn-js/dist/assets/diagram-js.css"
import "bpmn-js/dist/assets/bpmn-font/css/bpmn.css"

const route = useRoute()
const router = useRouter()

const instanceId = computed(() => route.params.instance)

const loading = ref(true)
const details = ref(null)

const activeTasks     = ref([])
const completingTask  = ref(null)   // task_id currently being completed
const completingAction = ref(null)  // action label being submitted
const logs = ref([])

const processVariables = computed(() => {
	if (!details.value || !details.value.workflow_state) return {}
	try {
		const state = (typeof details.value.workflow_state === 'string') 
			? JSON.parse(details.value.workflow_state) 
			: details.value.workflow_state
		
		return state.data || state || {}
	} catch (e) {
		console.warn("Failed to parse process variables:", e)
		return {}
	}
})

const bpmnXml = ref(null)
const canvasRef = ref(null)
const viewer = shallowRef(null)

const limitStart = ref(0)
const limitPageLength = 20
const hasMoreLogs = ref(true)
const logsLoading = ref(false)

const sortedLogs = computed(() => {
	// Sort by the actual task execution timestamp ascending (oldest event first)
	// This correctly reflects the process flow sequence regardless of DB insertion order.
	return [...logs.value].sort((a, b) => {
		const ta = new Date(a.timestamp || a.creation || 0).getTime()
		const tb = new Date(b.timestamp || b.creation || 0).getTime()
		return ta - tb
	})
});

onMounted(async () => {
	injectStyles()
	injectSvgMarker()
	await loadDetails()
	await loadLogs()
	loading.value = false
})

function injectStyles() {
	if (!document.getElementById("bpmn-marker-styles")) {
		const style = document.createElement("style");
		style.id = "bpmn-marker-styles";
		style.innerHTML = `
			/* Node Highlights */
			.highlight-done:not(.djs-connection) .djs-visual > :nth-child(1) {
				stroke: #16a34a !important; 
				fill: #dcfce7 !important;
				stroke-width: 2px !important;
			}
			.highlight-active:not(.djs-connection) .djs-visual > :nth-child(1) {
				stroke: #2563eb !important; 
				fill: #dbeafe !important;
				stroke-width: 2px !important;
			}
			.highlight-active:not(.djs-connection) .djs-shape {
				animation: active-pulse 2s infinite ease-in-out;
			}
			
			/* Flow Highlights */
			.highlight-flow-done.djs-connection .djs-visual > path {
				stroke: #16a34a !important;
				stroke-width: 2px !important;
				marker-end: url(#sequenceflow-arrow-green) !important;
			}

			@keyframes active-pulse {
				0% { filter: drop-shadow(0 0 2px rgba(37, 99, 235, 0.4)); }
				50% { filter: drop-shadow(0 0 8px rgba(37, 99, 235, 0.8)); }
				100% { filter: drop-shadow(0 0 2px rgba(37, 99, 235, 0.4)); }
			}
			
			/* Make zoom toolbar fit properly */
			.bpmn-canvas-container .djs-overlay-container {
				pointer-events: none;
			}
			.bpmn-canvas-container .djs-overlay {
				pointer-events: all;
			}
		`;
		document.head.appendChild(style);
	}
}

function injectSvgMarker() {
	if (!document.getElementById("bpmn-green-markers")) {
		const svgNS = "http://www.w3.org/2000/svg";
		const svg = document.createElementNS(svgNS, "svg");
		svg.id = "bpmn-green-markers";
		svg.style.position = "absolute";
		svg.style.width = "0";
		svg.style.height = "0";
		
		const defs = document.createElementNS(svgNS, "defs");
		
		const marker = document.createElementNS(svgNS, "marker");
		marker.setAttribute("id", "sequenceflow-arrow-green");
		marker.setAttribute("viewBox", "0 0 20 20");
		marker.setAttribute("refX", "11");
		marker.setAttribute("refY", "10");
		marker.setAttribute("markerWidth", "10");
		marker.setAttribute("markerHeight", "10");
		marker.setAttribute("orient", "auto");
		
		const path = document.createElementNS(svgNS, "path");
		path.setAttribute("d", "M 1 5 L 11 10 L 1 15 Z");
		path.setAttribute("fill", "#16a34a");
		path.setAttribute("stroke", "#16a34a");
		path.setAttribute("stroke-width", "1");
		path.setAttribute("stroke-linecap", "round");
		path.setAttribute("stroke-linejoin", "round");
		
		marker.appendChild(path);
		defs.appendChild(marker);
		svg.appendChild(defs);
		
		document.body.appendChild(svg);
	}
}

// Zoom Controls
function zoomIn() { if(viewer.value) viewer.value.get('canvas').zoom(viewer.value.get('canvas').zoom() * 1.2) }
function zoomOut() { if(viewer.value) Math.max(viewer.value.get('canvas').zoom() / 1.2, 0.1) && viewer.value.get('canvas').zoom(viewer.value.get('canvas').zoom() / 1.2) }
function resetZoom() { if(viewer.value) viewer.value.get('canvas').zoom(1) }
function fitViewport() { if(viewer.value) viewer.value.get('canvas').zoom('fit-viewport', 'auto') }

onUnmounted(() => {
	if (viewer.value) {
		viewer.value.destroy()
		viewer.value = null
	}
})

watch([logs, activeTasks, bpmnXml], () => {
	applyHighlights()
}, { deep: true })

watch([loading, canvasRef, bpmnXml], () => {
	if (!loading.value && canvasRef.value && bpmnXml.value && !viewer.value) {
		initViewer()
	}
})

async function loadDetails() {
	try {
		const res = await frappeRequest({
			url: "/api/method/frappe.client.get",
			method: "POST",
			params: { 
				doctype: "BPMN Process Instance",
				name: instanceId.value 
			}
		})
		details.value = res
		
		if (res && res.active_tasks) {
			activeTasks.value = res.active_tasks.filter(t => !t.status || t.status === "Waiting")
		} else {
			activeTasks.value = []
		}
		
		if (res && res.process_model) {
			loadProcessModelXml(res.process_model)
		}
	} catch (e) {
		console.error("Failed to load instance details:", e)
	}
}

async function loadProcessModelXml(modelName) {
	try {
		const res = await frappeRequest({
			url: "/api/method/one_bpmn.api.get_process_model",
			params: { name: modelName }
		})
		
		const data = res.message || res
		if (data && data.xml_content) {
			bpmnXml.value = decodeHtmlEntities(data.xml_content)
			// initViewer will be triggered by watch effect now
		}
	} catch (e) {
		console.error("Failed to load process model XML", e)
	}
}

function decodeHtmlEntities(text) {
	const textarea = document.createElement("textarea");
	textarea.innerHTML = text;
	return textarea.value;
}

async function initViewer() {
	if (!canvasRef.value || !bpmnXml.value) return;
	
	if (!viewer.value) {
		viewer.value = new NavigatedViewer({
			container: canvasRef.value,
			width: '100%',
			height: '100%'
		})
		
		viewer.value.get("eventBus").on("element.click", onElementClick)
		
		// Optional: Clear overlay if user clicks background or changes selection
		viewer.value.get("eventBus").on("canvas.click", () => {
			viewer.value.get("overlays").clear();
		})
	}
	
	try {
		await viewer.value.importXML(bpmnXml.value)
		
		setTimeout(() => {
			try {
				const canvas = viewer.value.get("canvas")
				canvas.zoom("fit-viewport", "auto")
				applyHighlights()
			} catch (err) {
				console.warn("Could not fit viewport - container may be hidden:", err)
			}
		}, 100)
	} catch (err) {
		console.error("Error rendering BPMN sequence", err)
	}
}

function applyHighlights() {
	if (!viewer.value || !bpmnXml.value) return;
	try {
		const canvas = viewer.value.get("canvas");
		const elementRegistry = viewer.value.get("elementRegistry");
		
		const doneTasks = new Set(logs.value.filter(l => l.action === "Completed").map(l => l.task_id))
		doneTasks.forEach(taskId => {
			try {
				canvas.addMarker(taskId, "highlight-done")
			} catch(e) {}
		})
		
		const currentActiveTasks = new Set(activeTasks.value.map(t => t.task_id))
		currentActiveTasks.forEach(taskId => {
			try {
				canvas.addMarker(taskId, "highlight-active")
			} catch(e) {}
		})

		// Sequence Flow + StartEvent Highlights
		if (elementRegistry) {
			elementRegistry.filter(e => e.type === "bpmn:SequenceFlow" || e.type === "bpmn:StartEvent").forEach(element => {
				try {
					if (element.type === "bpmn:StartEvent") {
						// Highlight the StartEvent circle green unconditionally since instance is active/done
						canvas.addMarker(element.id, "highlight-done");
					} else {
						// It's a Sequence Flow
						const flow = element;
						const sourceId = flow.source && flow.source.id;
						const targetId = flow.target && flow.target.id;
						
						const sourceDone = doneTasks.has(sourceId) || (flow.source && flow.source.type === "bpmn:StartEvent");
						const targetReached = doneTasks.has(targetId) || currentActiveTasks.has(targetId);
						
						if (targetReached || (sourceDone && flow.target && flow.target.type.includes("EndEvent"))) {
							canvas.addMarker(flow.id, "highlight-flow-done");
						}
					}
				} catch(e) {}
			})
		}
	} catch(err) {
		console.warn("Could not apply highlights:", err);
	}
}

function onElementClick(e) {
	const elementId = e.element.id;
	const activeTask = activeTasks.value.find(t => t.task_id === elementId);
	const doneLogs = logs.value.filter(l => l.task_id === elementId && l.action === "Completed");
	
	if (!viewer.value) return;
	
	const overlays = viewer.value.get("overlays");
	overlays.clear(); // Clear previous overlays
	
	if (activeTask || doneLogs.length > 0) {
		const log = doneLogs.length > 0 ? doneLogs[0] : null;
		const isDone = !!log;
		
		const name = e.element.businessObject?.name || elementId;
		const status = isDone ? "Completed" : "Active";
		const themeClass = isDone ? "bg-green-100 text-green-800 border-green-200" : "bg-blue-100 text-blue-800 border-blue-200";
		
		let metaHtml = "";
		if (isDone) {
			metaHtml = `<div class="text-xs text-gray-600 mt-1">Completed by: ${log.user || 'System'}</div>
						<div class="text-xs text-gray-500">${formatDateTime(log.timestamp)}</div>`;
		} else if (activeTask) {
			metaHtml = `<div class="text-xs text-gray-600 mt-1">Started: ${formatDateTime(activeTask.started_at)}</div>`;
			if (activeTask.assigned_user) {
				metaHtml += `<div class="text-xs text-gray-500 mt-1">Assignee: ${activeTask.assigned_user}</div>`;
			} else if (activeTask.assigned_role) {
				metaHtml += `<div class="text-xs text-gray-500 mt-1">Role: ${activeTask.assigned_role}</div>`;
			}
		}
		
		const html = document.createElement("div");
		html.className = `p-3 bg-white border shadow-lg rounded w-64 z-50 pointer-events-auto`;
		html.innerHTML = `
			<div class="flex items-center justify-between mb-2">
				<div class="font-semibold text-gray-900 text-sm truncate pr-2" title="${name}">${name}</div>
				<span class="text-[10px] uppercase font-bold px-2 py-0.5 rounded border ${themeClass}">${status}</span>
			</div>
			${metaHtml}
		`;
		
		const closeBtn = document.createElement("button");
		closeBtn.innerHTML = "&times;";
		closeBtn.className = "absolute top-1 right-2 text-gray-400 hover:text-gray-600 text-lg leading-none bg-transparent hover:bg-gray-100 rounded px-1";
		closeBtn.onclick = (event) => {
			event.stopPropagation();
			overlays.clear();
		};
		html.appendChild(closeBtn);
		
		// Determine position slightly depending on element size or just center bottom
		overlays.add(elementId, {
			position: { bottom: 0, left: 0 },
			html: html
		});
	}
}

// ── Task Decision Helpers ───────────────────────────────────────────────────

/** Parse comma-separated task_actions string into trimmed labels */
function getTaskActions(task) {
	const raw = task.task_actions || ''
	return raw.split(',').map(a => a.trim()).filter(Boolean)
}

/** Colour-code common action verbs */
function getActionButtonClass(action) {
	const lower = action.toLowerCase()
	if (['approve', 'approved', 'accept', 'yes', 'confirm'].some(k => lower.includes(k)))
		return 'bg-green-50 hover:bg-green-100 text-green-800 border-green-300 disabled:opacity-50'
	if (['reject', 'rejected', 'decline', 'no', 'deny', 'refuse'].some(k => lower.includes(k)))
		return 'bg-red-50 hover:bg-red-100 text-red-800 border-red-300 disabled:opacity-50'
	return 'bg-blue-50 hover:bg-blue-100 text-blue-800 border-blue-300 disabled:opacity-50'
}

/**
 * Complete a User Task, submitting the chosen action label as the "decision"
 * workflow variable.  Gateway conditions can then check: decision == "Approve"
 */
async function completeTask(task, action) {
	if (completingTask.value) return   // prevent double-click during loading
	completingTask.value   = task.task_id
	completingAction.value = action
	try {
		const data = action ? JSON.stringify({ decision: action }) : '{}'
		await frappeRequest({
			url:    '/api/method/one_bpmn.api.complete_task',
			method: 'POST',
			params: {
				instance_name: instanceId.value,
				task_id:       task.task_id,
				data,
			},
		})
		// Refresh everything — new active tasks, updated diagram highlights, history
		logs.value       = []
		limitStart.value  = 0
		hasMoreLogs.value = true
		await loadDetails()
		await loadLogs()
	} catch (err) {
		console.error('Failed to complete task:', err)
	} finally {
		completingTask.value   = null
		completingAction.value = null
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
				limit_page_length: limitPageLength
			}
		})
		if (res && res.length > 0) {
			logs.value = [...logs.value, ...res]
			limitStart.value += res.length
			if (res.length < limitPageLength) {
				hasMoreLogs.value = false
			}
		} else {
			hasMoreLogs.value = false
		}
	} catch (e) {
		console.error("Failed to load instance logs:", e)
	} finally {
		logsLoading.value = false
	}
}

function getContextDocumentLink() {
	if (details.value?.context_doctype && details.value?.context_docname) {
		return `/app/${details.value.context_doctype.toLowerCase().replace(/ /g, '-')}/${details.value.context_docname}`
	}
	return "#"
}

function getStatusTheme(status) {
	switch (status) {
		case "Completed": return "green"
		case "Active": return "blue"
		case "Errored": return "red"
		case "Cancelled": return "gray"
		default: return "gray"
	}
}

function getLogActionTheme(action) {
	switch (action) {
		case "Completed": return "green"
		case "Started": return "blue"
		case "Errored": return "red"
		case "Skipped": return "gray"
		default: return "gray"
	}
}

function formatDateTime(dateStr) {
	if (!dateStr) return "-"
	return dayjs(dateStr).format("DD-MM-YYYY hh:mm A")
}
</script>

<style>
/* Custom scrollbar for sleek panels */
.custom-scrollbar::-webkit-scrollbar {
  width: 6px;
  height: 6px;
}
.custom-scrollbar::-webkit-scrollbar-track {
  background: rgba(0,0,0,0.02); 
}
.custom-scrollbar::-webkit-scrollbar-thumb {
  background: rgba(0,0,0,0.1); 
  border-radius: 10px;
}
.custom-scrollbar::-webkit-scrollbar-thumb:hover {
  background: rgba(0,0,0,0.2); 
}
</style>
