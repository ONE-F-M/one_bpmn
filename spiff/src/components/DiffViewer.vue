<template>
	<div class="diff-viewer-root flex flex-col h-full">
		<!-- Legend Bar -->
		<div class="flex items-center gap-4 px-4 py-2 bg-gray-50 border-b border-gray-200 text-xs shrink-0">
			<span class="font-semibold text-gray-700">Changes:</span>
			<span class="flex items-center gap-1.5">
				<span class="w-3 h-3 rounded-sm bg-green-100 border border-green-500"></span>
				<span class="text-gray-600">Added ({{ stats.added }})</span>
			</span>
			<span class="flex items-center gap-1.5">
				<span class="w-3 h-3 rounded-sm bg-red-100 border border-red-500"></span>
				<span class="text-gray-600">Removed ({{ stats.removed }})</span>
			</span>
			<span class="flex items-center gap-1.5">
				<span class="w-3 h-3 rounded-sm bg-amber-100 border border-amber-500"></span>
				<span class="text-gray-600">Changed ({{ stats.changed }})</span>
			</span>
			<span class="flex items-center gap-1.5">
				<span class="w-3 h-3 rounded-sm bg-purple-100 border border-purple-500"></span>
				<span class="text-gray-600">Layout ({{ stats.layoutChanged }})</span>
			</span>
			<span class="ml-auto text-gray-400" v-if="stats.total === 0">No differences found</span>
		</div>

		<!-- Side-by-Side Viewers -->
		<div class="flex-1 flex overflow-hidden min-h-0">
			<!-- Left: Old Version -->
			<div class="flex-1 flex flex-col border-r border-gray-200 min-w-0">
				<div class="px-3 py-1.5 bg-red-50 border-b border-red-200 text-xs font-medium text-red-700 shrink-0 flex items-center gap-1.5">
					<Icon icon="lucide:clock" class="w-3.5 h-3.5" />
					{{ oldLabel || 'Previous Version' }}
				</div>
				<div ref="canvasOld" class="flex-1 diff-canvas"></div>
			</div>

			<!-- Right: New/Current Version -->
			<div class="flex-1 flex flex-col min-w-0">
				<div class="px-3 py-1.5 bg-green-50 border-b border-green-200 text-xs font-medium text-green-700 shrink-0 flex items-center gap-1.5">
					<Icon icon="lucide:check-circle" class="w-3.5 h-3.5" />
					{{ newLabel || 'Current Version' }}
				</div>
				<div ref="canvasNew" class="flex-1 diff-canvas"></div>
			</div>
		</div>

		<!-- Changes Overview Panel -->
		<div
			v-if="changesList.length > 0"
			class="shrink-0 border-t border-gray-200 bg-white"
		>
			<button
				@click="showOverview = !showOverview"
				class="w-full flex items-center justify-between px-4 py-2 text-xs font-medium text-gray-600 hover:bg-gray-50 transition-colors"
			>
				<span>
					<Icon
						:icon="showOverview ? 'lucide:chevron-down' : 'lucide:chevron-right'"
						class="w-3.5 h-3.5 inline mr-1"
					/>
					Changes Overview ({{ stats.total }})
				</span>
			</button>
			<div
				v-show="showOverview"
				class="max-h-48 overflow-auto border-t border-gray-100"
			>
				<table class="w-full text-xs">
					<thead class="bg-gray-50 sticky top-0">
						<tr>
							<th class="text-left px-3 py-1.5 text-gray-500 font-medium">#</th>
							<th class="text-left px-3 py-1.5 text-gray-500 font-medium">Name</th>
							<th class="text-left px-3 py-1.5 text-gray-500 font-medium">Type</th>
							<th class="text-left px-3 py-1.5 text-gray-500 font-medium">Change</th>
						</tr>
					</thead>
					<tbody>
						<tr
							v-for="(item, idx) in changesList"
							:key="item.id"
							class="cursor-pointer hover:bg-blue-50 transition-colors border-t border-gray-50"
							:class="{ 'bg-blue-50': highlightedId === item.id }"
							@click="panToElement(item)"
							@mouseenter="highlightElement(item)"
							@mouseleave="unhighlightElement(item)"
						>
							<td class="px-3 py-1.5 text-gray-400">{{ idx + 1 }}</td>
							<td class="px-3 py-1.5 text-gray-800 font-medium">{{ item.name || '—' }}</td>
							<td class="px-3 py-1.5 text-gray-500">{{ item.type }}</td>
							<td class="px-3 py-1.5">
								<span
									:class="[
										'inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-semibold',
										changeClassMap[item.changeClass]
									]"
								>{{ item.change }}</span>
							</td>
						</tr>
					</tbody>
				</table>
			</div>
		</div>
	</div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted, nextTick } from "vue";
import { Icon } from "@iconify/vue";
import {
	computeDiff,
	applyDiffMarkers,
	clearDiffMarkers,
	syncViewers,
	buildChangesList as buildChanges,
} from "@/composables/useBpmnDiff";

// Import bpmn-js CSS (may already be loaded by BpmnEditor, but safe to re-import)
import "bpmn-js/dist/assets/diagram-js.css";
import "bpmn-js/dist/assets/bpmn-font/css/bpmn.css";

const props = defineProps({
	oldXml: { type: String, required: true },
	newXml: { type: String, required: true },
	oldLabel: { type: String, default: "Previous Version" },
	newLabel: { type: String, default: "Current Version" },
});

const canvasOld = ref(null);
const canvasNew = ref(null);
const showOverview = ref(true);
const highlightedId = ref(null);

let viewerOld = null;
let viewerNew = null;
let teardownSync = null;
let diffResult = null;

const changesList = ref([]);

const stats = computed(() => {
	const r = diffResult || {};
	const added = Object.keys(r._added || {}).length;
	const removed = Object.keys(r._removed || {}).length;
	const changed = Object.keys(r._changed || {}).length;
	const layoutChanged = Object.keys(r._layoutChanged || {}).length;
	return { added, removed, changed, layoutChanged, total: added + removed + changed + layoutChanged };
});

const changeClassMap = {
	added: "bg-green-100 text-green-700",
	removed: "bg-red-100 text-red-700",
	changed: "bg-amber-100 text-amber-700",
	"layout-changed": "bg-purple-100 text-purple-700",
};

onMounted(async () => {
	await nextTick();

	// Dynamically import NavigatedViewer to keep the bundle small for non-diff usage
	const { default: NavigatedViewer } = await import("bpmn-js/lib/NavigatedViewer");

	viewerOld = new NavigatedViewer({
		container: canvasOld.value,
	});

	viewerNew = new NavigatedViewer({
		container: canvasNew.value,
	});

	// Sync pan/zoom
	teardownSync = syncViewers(viewerOld, viewerNew);

	try {
		await viewerOld.importXML(props.oldXml);
		await viewerNew.importXML(props.newXml);

		// Compute diff
		diffResult = computeDiff(viewerOld, viewerNew);
		changesList.value = buildChanges(diffResult);

		// Apply visual markers
		applyDiffMarkers(viewerOld, viewerNew, diffResult);

		// Fit both to viewport
		try {
			viewerOld.get("canvas").zoom("fit-viewport");
		} catch (_) {}
		try {
			viewerNew.get("canvas").zoom("fit-viewport");
		} catch (_) {}
	} catch (err) {
		console.error("[DiffViewer] Failed to import XML or compute diff:", err);
	}
});

onUnmounted(() => {
	if (teardownSync) teardownSync();
	if (viewerOld) viewerOld.destroy();
	if (viewerNew) viewerNew.destroy();
});

function panToElement(item) {
	const viewer = item.changeClass === "removed" ? viewerOld : viewerNew;
	if (!viewer) return;

	const element = viewer.get("elementRegistry").get(item.id);
	if (!element) return;

	const canvas = viewer.get("canvas");
	let x, y;

	if (element.waypoints) {
		x = element.waypoints[0].x;
		y = element.waypoints[0].y;
	} else {
		x = element.x + element.width / 2;
		y = element.y + element.height / 2;
	}

	const containerEl = item.changeClass === "removed" ? canvasOld.value : canvasNew.value;
	const rect = containerEl.getBoundingClientRect();

	canvas.viewbox({
		x: x - rect.width / 2,
		y: y - rect.height / 2,
		width: rect.width,
		height: rect.height,
	});

	highlightedId.value = item.id;
}

function highlightElement(item) {
	if (item.changeClass === "removed") {
		safeHighlight(viewerOld, item.id);
	} else if (item.changeClass === "added") {
		safeHighlight(viewerNew, item.id);
	} else {
		safeHighlight(viewerOld, item.id);
		safeHighlight(viewerNew, item.id);
	}
}

function unhighlightElement(item) {
	if (item.changeClass === "removed") {
		safeUnhighlight(viewerOld, item.id);
	} else if (item.changeClass === "added") {
		safeUnhighlight(viewerNew, item.id);
	} else {
		safeUnhighlight(viewerOld, item.id);
		safeUnhighlight(viewerNew, item.id);
	}
}

function safeHighlight(viewer, id) {
	try { viewer.get("canvas").addMarker(id, "highlight"); } catch (_) {}
}

function safeUnhighlight(viewer, id) {
	try { viewer.get("canvas").removeMarker(id, "highlight"); } catch (_) {}
}
</script>

<style>
/* ── Diff Canvas ────────────────────────────── */
.diff-canvas {
	background: #fafafa;
	min-height: 200px;
}

/* ── Diff Visual Markers ──────────────────────── */

/* Added elements — green */
.diff-added:not(.djs-connection) .djs-visual > :nth-child(1) {
	fill: #dcfce7 !important;
	stroke: #16a34a !important;
	stroke-width: 2px !important;
}
.diff-added.djs-connection .djs-visual > :nth-child(1) {
	stroke: #16a34a !important;
	stroke-width: 2.5px !important;
}

/* Removed elements — red */
.diff-removed:not(.djs-connection) .djs-visual > :nth-child(1) {
	fill: #fee2e2 !important;
	stroke: #dc2626 !important;
	stroke-width: 2px !important;
}
.diff-removed.djs-connection .djs-visual > :nth-child(1) {
	stroke: #dc2626 !important;
	stroke-width: 2.5px !important;
}

/* Changed elements — amber/yellow */
.diff-changed:not(.djs-connection) .djs-visual > :nth-child(1) {
	fill: #fef3c7 !important;
	stroke: #d97706 !important;
	stroke-width: 2px !important;
}
.diff-changed.djs-connection .djs-visual > :nth-child(1) {
	stroke: #d97706 !important;
	stroke-width: 2.5px !important;
}

/* Layout changed — purple */
.diff-layout-changed:not(.djs-connection) .djs-visual > :nth-child(1) {
	fill: #ede9fe !important;
	stroke: #7c3aed !important;
	stroke-width: 2px !important;
}
.diff-layout-changed.djs-connection .djs-visual > :nth-child(1) {
	stroke: #7c3aed !important;
	stroke-width: 2.5px !important;
}

/* Hover highlight */
.highlight:not(.djs-connection) .djs-visual > :nth-child(1) {
	stroke: #2563eb !important;
	stroke-width: 3px !important;
}
.highlight.djs-connection .djs-visual > :nth-child(1) {
	stroke: #2563eb !important;
	stroke-width: 3px !important;
}

/* ── Overlay Badges ──────────────────────────── */
.diff-overlay-badge {
	display: inline-flex;
	align-items: center;
	justify-content: center;
	min-width: 18px;
	height: 18px;
	border-radius: 9px;
	font-size: 11px;
	font-weight: 700;
	line-height: 1;
	box-shadow: 0 1px 3px rgba(0, 0, 0, 0.2);
}

.marker-added {
	background: #16a34a;
	color: white;
}

.marker-removed {
	background: #dc2626;
	color: white;
}

.marker-changed {
	background: #d97706;
	color: white;
}

.marker-layout-changed {
	background: #7c3aed;
	color: white;
}

/* ── Hide palette and context pad in diff viewers ── */
.diff-canvas .djs-palette,
.diff-canvas .djs-context-pad {
	display: none !important;
}
</style>
