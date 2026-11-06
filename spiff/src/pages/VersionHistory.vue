<template>
	<!-- Full-page version history (Google-Docs-style): preview + history rail -->
	<div class="h-full flex flex-col bg-gray-50">
		<!-- Header -->
		<header class="bg-white border-b px-4 py-3 flex items-center gap-3 shrink-0">
			<button
				@click="goBack"
				class="w-8 h-8 flex items-center justify-center rounded hover:bg-gray-100 text-gray-600"
				title="Back to editor"
			>
				<Icon icon="lucide:arrow-left" class="w-5 h-5" />
			</button>
			<div class="min-w-0">
				<h1 class="text-base font-semibold text-gray-900 truncate">Version history</h1>
				<p class="text-xs text-gray-500 truncate">{{ diagramTitle || diagram }}</p>
			</div>
		</header>

		<!-- Inline error banner -->
		<div
			v-if="errorMessage"
			class="bg-red-50 border-b border-red-200 px-4 py-2 text-sm text-red-700 flex items-center gap-2 shrink-0"
		>
			<Icon icon="lucide:alert-circle" class="w-4 h-4 shrink-0" />
			<span class="flex-1">{{ errorMessage }}</span>
			<button class="text-red-500 hover:text-red-700" @click="errorMessage = ''">
				<Icon icon="lucide:x" class="w-4 h-4" />
			</button>
		</div>

		<!-- Body: preview + history rail -->
		<div class="flex-1 flex min-h-0">
			<!-- Read-only preview of the selected version -->
			<div class="flex-1 flex flex-col min-w-0">
				<!-- Preview toolbar -->
				<div class="flex items-center gap-3 px-4 py-2 bg-white border-b border-gray-200 shrink-0">
					<div class="min-w-0">
						<div class="text-sm font-medium text-gray-900 truncate flex items-center gap-1.5">
							<Icon
								v-if="selectedVersion && !selectedIsCurrent"
								icon="lucide:lock"
								class="w-3.5 h-3.5 text-gray-400 shrink-0"
							/>
							{{ previewLabel }}
						</div>
						<div v-if="previewSub" class="text-xs text-gray-500 truncate">{{ previewSub }}</div>
					</div>

					<div class="ml-auto flex items-center gap-1">
						<!-- Zoom controls -->
						<button
							@click="zoomOut"
							class="p-1.5 rounded hover:bg-gray-100 text-gray-600 transition-colors"
							title="Zoom out"
						>
							<Icon icon="lucide:minus" class="w-4 h-4" />
						</button>
						<button
							@click="fit"
							class="px-2 py-1 rounded hover:bg-gray-100 text-gray-700 text-sm font-medium min-w-[48px] text-center transition-colors"
							title="Fit to screen"
						>
							{{ zoomLevel }}%
						</button>
						<button
							@click="zoomIn"
							class="p-1.5 rounded hover:bg-gray-100 text-gray-600 transition-colors"
							title="Zoom in"
						>
							<Icon icon="lucide:plus" class="w-4 h-4" />
						</button>

						<!-- Restore (only for non-current versions) -->
						<Button
							v-if="selectedVersion && !selectedIsCurrent"
							variant="solid"
							:loading="restoring"
							class="ml-2"
							@click="restore"
						>
							Restore this version
						</Button>
					</div>
				</div>

				<!-- Canvas -->
				<div class="relative flex-1 min-h-0 bg-gray-50">
					<div ref="canvasRef" class="absolute inset-0"></div>
					<div
						v-if="loadingPreview"
						class="absolute inset-0 flex items-center justify-center text-gray-400 text-sm bg-gray-50/70"
					>
						<div class="animate-spin rounded-full h-6 w-6 border-b-2 border-gray-400 mr-2"></div>
						Loading preview…
					</div>
					<div
						v-else-if="isEmptyDiagram"
						class="absolute inset-0 flex flex-col items-center justify-center text-gray-400 pointer-events-none"
					>
						<Icon icon="lucide:layout-grid" class="w-14 h-14 mb-3 opacity-40" />
						<p class="text-sm">This version has no diagram content.</p>
					</div>
				</div>
			</div>

			<!-- History rail (reused panel) -->
			<VersionHistoryPanel
				:modelName="diagram"
				:getCurrentXml="getLatestXml"
				@close="goBack"
				@error="onError"
				@restored="onRestored"
				@select-version="onSelectVersion"
			/>
		</div>
	</div>
</template>

<script setup>
import { ref, onMounted, onBeforeUnmount, nextTick } from "vue";
import { useRouter } from "vue-router";
import { frappeRequest } from "frappe-ui";
import { Icon } from "@iconify/vue";
import { dayjs } from "@/dayjs";
import VersionHistoryPanel from "@/components/VersionHistoryPanel.vue";
import "bpmn-js/dist/assets/diagram-js.css";
import "bpmn-js/dist/assets/bpmn-font/css/bpmn.css";

const props = defineProps({
	process: { type: String, required: true },
	diagram: { type: String, required: true },
});

const router = useRouter();
const canvasRef = ref(null);
const previewLabel = ref("");
const previewSub = ref("");
const diagramTitle = ref("");
const errorMessage = ref("");
const loadingPreview = ref(true);
const isEmptyDiagram = ref(false);
const zoomLevel = ref(100);

const selectedVersion = ref(null); // snapshot doc name
const selectedIsCurrent = ref(true);
const restoring = ref(false);

let viewer = null;
let latestXml = "";

onMounted(async () => {
	await initViewer();
	await fetchLatest();
	await showLatest();
});

onBeforeUnmount(() => {
	if (viewer) {
		try { viewer.destroy(); } catch (_) { /* ignore */ }
		viewer = null;
	}
});

async function initViewer() {
	await nextTick();
	// Lightweight read-only viewer (no editing chrome) — keeps the page clean.
	const { default: NavigatedViewer } = await import("bpmn-js/lib/NavigatedViewer");
	viewer = new NavigatedViewer({ container: canvasRef.value });
}

async function fetchLatest() {
	try {
		const res = await frappeRequest({
			url: "/api/method/one_bpmn.api.process_map_api.get_process_model",
			params: { name: props.diagram },
		});
		const data = res.message || res;
		latestXml = data?.xml_content || "";
		diagramTitle.value = data?.title || "";

		// Prefer the most recent snapshot (the history's "Current version") for the
		// default preview. The model's bpmn_xml can lag behind its snapshots (e.g.
		// a freshly ProsAlly-generated diagram whose autosave hasn't landed yet),
		// which would otherwise show an empty "Latest version" even though the
		// timeline already has content.
		const snapXml = await fetchCurrentSnapshotXml();
		if (snapXml) latestXml = snapXml;
	} catch (error) {
		console.error("Failed to load diagram:", error);
		onError({ message: "Failed to load the diagram." });
	}
}

// Resolve the XML of the newest snapshot in the history (the "Current version").
async function fetchCurrentSnapshotXml() {
	try {
		const res = await frappeRequest({
			url: "/api/method/one_bpmn.api.version_history.get_edit_history",
			params: { model_name: props.diagram },
		});
		const groups = res.message || res || [];
		const head = groups[0]?.head;
		if (!head) return "";
		const snapRes = await frappeRequest({
			url: "/api/method/one_bpmn.api.version_history.get_snapshot_xml",
			params: { version_name: head },
		});
		return (snapRes.message || snapRes)?.xml_content || "";
	} catch (error) {
		console.error("Failed to load current snapshot:", error);
		return "";
	}
}

async function showLatest() {
	selectedVersion.value = null;
	selectedIsCurrent.value = true;
	previewLabel.value = "Latest version";
	previewSub.value = "";
	await renderXml(latestXml);
}

// Provides the latest diagram XML to the panel (for "Compare with current").
async function getLatestXml() {
	if (!latestXml) await fetchLatest();
	return latestXml;
}

async function onSelectVersion(item) {
	// item: { name, is_current, version_name, timestamp, author }
	selectedVersion.value = item.name;
	selectedIsCurrent.value = !!item.is_current;
	try {
		const res = await frappeRequest({
			url: "/api/method/one_bpmn.api.version_history.get_snapshot_xml",
			params: { version_name: item.name },
		});
		const snap = res.message || res;
		previewLabel.value = item.is_current
			? "Latest version"
			: (item.version_name || snap.version_name || formatTime(item.timestamp));
		previewSub.value = [snap.author || item.author, formatTime(snap.timestamp || item.timestamp)]
			.filter(Boolean)
			.join(" · ");
		await renderXml(snap?.xml_content || "");
	} catch (error) {
		console.error("Failed to preview version:", error);
		onError({ message: "Failed to preview this version." });
	}
}

async function renderXml(xml) {
	if (!viewer) return;
	loadingPreview.value = true;
	isEmptyDiagram.value = false;
	try {
		if (!xml) {
			isEmptyDiagram.value = true;
			return;
		}
		await viewer.importXML(xml);
		fit();
		// Detect an essentially empty diagram (no flow elements drawn).
		const registry = viewer.get("elementRegistry");
		const drawn = registry.filter((el) => el.type && el.type !== "bpmn:Process" && el.type !== "label");
		isEmptyDiagram.value = drawn.length === 0;
	} catch (error) {
		console.error("Failed to render version XML:", error);
		isEmptyDiagram.value = true;
	} finally {
		loadingPreview.value = false;
	}
}

function canvas() {
	return viewer?.get("canvas");
}

function syncZoom() {
	const c = canvas();
	if (c) zoomLevel.value = Math.round(c.zoom() * 100);
}

function fit() {
	const c = canvas();
	if (!c) return;
	c.zoom("fit-viewport", "auto");
	syncZoom();
}

function zoomIn() {
	const c = canvas();
	if (!c) return;
	c.zoom(c.zoom() * 1.15);
	syncZoom();
}

function zoomOut() {
	const c = canvas();
	if (!c) return;
	c.zoom(c.zoom() / 1.15);
	syncZoom();
}

async function restore() {
	if (!selectedVersion.value || restoring.value) return;
	if (!window.confirm("Restore this version? The current diagram will be replaced (a snapshot of it is kept in history).")) {
		return;
	}
	restoring.value = true;
	try {
		await frappeRequest({
			url: "/api/method/one_bpmn.api.version_history.restore_version",
			params: { version_name: selectedVersion.value },
		});
		goBack();
	} catch (error) {
		console.error("Restore failed:", error);
		onError({ message: "Failed to restore this version." });
	} finally {
		restoring.value = false;
	}
}

function onRestored() {
	// After restoring from the panel, return to the editor.
	goBack();
}

function onError(e) {
	errorMessage.value = e?.message || "Something went wrong.";
}

function formatTime(ts) {
	if (!ts) return "";
	return dayjs(ts).format("MMM D, h:mm A");
}

function goBack() {
	router.push({ name: "DiagramEditor", params: { process: props.process, diagram: props.diagram } });
}
</script>
