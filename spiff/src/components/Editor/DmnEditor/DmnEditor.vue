<template>
	<div class="dmn-editor-root" ref="rootEl">
		<!-- Toolbar -->
		<div class="dmn-editor-toolbar flex items-center justify-between px-4 py-2 border-b border-gray-200 bg-gray-50/50 shrink-0">
			<div class="flex items-center gap-3">
				<div class="flex items-center gap-1.5 text-sm font-medium text-gray-700">
					<svg class="w-4 h-4 text-indigo-500" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
						<rect x="3" y="3" width="7" height="7" rx="1" />
						<rect x="14" y="3" width="7" height="7" rx="1" />
						<rect x="8.5" y="14" width="7" height="7" rx="1" />
						<line x1="6.5" y1="10" x2="6.5" y2="14" />
						<line x1="6.5" y1="14" x2="12" y2="14" />
						<line x1="17.5" y1="10" x2="17.5" y2="14" />
						<line x1="17.5" y1="14" x2="12" y2="14" />
					</svg>
					Decision Model Editor
				</div>

				<div class="w-px h-5 bg-gray-200"></div>

				<!-- Current view indicator -->
				<div class="flex items-center gap-1.5 text-xs text-gray-500">
					<span class="px-2 py-0.5 rounded-full text-[10px] font-bold uppercase tracking-wider"
						:class="activeViewClass"
					>
						{{ activeViewLabel }}
					</span>
				</div>
			</div>

			<!-- Save status -->
			<div class="flex items-center gap-2">
				<div v-if="saveStatusText"
					class="dmn-save-status text-xs font-medium transition-colors"
					:class="saveStatusClass"
				>
					{{ saveStatusText }}
				</div>
			</div>
		</div>

		<!-- DMN Container -->
		<div ref="containerEl" class="dmn-container flex-1 min-h-0"></div>
	</div>
</template>

<script setup>
import { ref, onMounted, onBeforeUnmount } from "vue";

// dmn-js CSS — must be imported for proper rendering
import "dmn-js/dist/assets/diagram-js.css";
import "dmn-js/dist/assets/dmn-js-shared.css";
import "dmn-js/dist/assets/dmn-js-drd.css";
import "dmn-js/dist/assets/dmn-js-decision-table.css";
import "dmn-js/dist/assets/dmn-js-decision-table-controls.css";
import "dmn-js/dist/assets/dmn-js-literal-expression.css";
import "dmn-js/dist/assets/dmn-js-boxed-expression.css";
import "dmn-js/dist/assets/dmn-js-boxed-expression-controls.css";
import "dmn-js/dist/assets/dmn-font/css/dmn.css";

// Custom overrides
import "@/dmn-editor.css";

const props = defineProps({
	initialXml: {
		type: String,
		default: "",
	},
	readonly: {
		type: Boolean,
		default: false,
	},
});

const emit = defineEmits(["xml-changed", "view-changed"]);

const rootEl = ref(null);
const containerEl = ref(null);
const saveStatusText = ref("");
const saveStatusClass = ref("");
const activeViewLabel = ref("DRD");
const activeViewClass = ref("bg-indigo-100 text-indigo-700");

let modeler = null;
let autosaveTimer = null;

// ── View label mapping ──────────────────────────────────────────────
const VIEW_CONFIG = {
	drd: { label: "DRD", className: "bg-indigo-100 text-indigo-700" },
	decisionTable: { label: "Decision Table", className: "bg-emerald-100 text-emerald-700" },
	literalExpression: { label: "Literal Expression", className: "bg-amber-100 text-amber-700" },
	boxedExpression: { label: "Boxed Expression", className: "bg-violet-100 text-violet-700" },
};

// ── Lifecycle ───────────────────────────────────────────────────────
let isDestroyed = false;

onMounted(() => {
	// dmn-js requires a container with non-zero dimensions. When the
	// DmnEditor lives inside a frappe-ui Dialog that uses CSS transitions,
	// the container may still have zero height at the instant onMounted
	// fires. Deferring initialisation by one animation frame + a small
	// safety margin ensures the Dialog layout has settled.
	requestAnimationFrame(() => {
		setTimeout(() => initModeler(), 50);
	});
});

async function initModeler() {
	if (isDestroyed || !containerEl.value) return;

	// Dynamically import DmnJS Modeler to avoid SSR issues
	const { default: DmnJS } = await import("dmn-js/lib/Modeler");

	if (isDestroyed || !containerEl.value) return; // guard after async gap

	// dmn-js v17: keyboard.bindTo was removed — keyboard binding is now
	// implicit via the container. Do NOT pass common.keyboard.bindTo.
	modeler = new DmnJS({
		container: containerEl.value,
	});

	// Listen for view changes (DRD <-> Decision Table)
	modeler.on("views.changed", (event) => {
		const viewId = event.activeView?.type || "drd";
		const config = VIEW_CONFIG[viewId] || VIEW_CONFIG.drd;
		activeViewLabel.value = config.label;
		activeViewClass.value = config.className;
		emit("view-changed", viewId);
	});

	// ── Change listener ────────────────────────────────────────────
	// The Manager's eventBus does NOT proxy commandStack.changed from
	// child viewers. We hook in two places for reliability:
	// 1. viewer.created — fires once when each viewer type is first created
	// 2. views.changed — fires on every view switch, lets us re-attach
	const attachedViewers = new Set();

	function attachToViewer(viewer, label) {
		if (!viewer || attachedViewers.has(viewer)) return;
		try {
			const viewerEventBus = viewer.get("eventBus");
			viewerEventBus.on("commandStack.changed", onCommandStackChanged);
			attachedViewers.add(viewer);
			console.log(`[DmnEditor] ✅ Attached commandStack.changed to ${label}`);
		} catch (e) {
			console.warn(`[DmnEditor] ⚠ Failed to attach to ${label}:`, e);
		}
	}

	if (!props.readonly) {
		// Hook 1: when a viewer is first created
		modeler.on("viewer.created", ({ type, viewer }) => {
			console.log(`[DmnEditor] viewer.created: ${type}`);
			attachToViewer(viewer, `viewer.created:${type}`);
		});

		// Hook 2: on every view switch, try the active viewer
		modeler.on("views.changed", ({ activeView }) => {
			if (!activeView) return;
			const viewer = modeler.getActiveViewer();
			if (viewer) {
				attachToViewer(viewer, `views.changed:${activeView.type}`);
			}
		});
	}

	// Import the initial XML
	const xmlToLoad = props.initialXml || getDefaultDmnXml();
	try {
		await modeler.importXML(xmlToLoad);
		console.log("[DmnEditor] importXML complete");
	} catch (err) {
		console.error("[DmnEditor] Failed to import DMN XML:", err);
	}
}

onBeforeUnmount(() => {
	isDestroyed = true;
	if (autosaveTimer) clearTimeout(autosaveTimer);
	if (modeler) {
		modeler.destroy();
		modeler = null;
	}
});

// ── Debounced autosave handler ──────────────────────────────────────
function onCommandStackChanged() {
	console.log("[DmnEditor] 🔥 commandStack.changed fired!");
	if (autosaveTimer) clearTimeout(autosaveTimer);
	saveStatusText.value = "Unsaved changes";
	saveStatusClass.value = "text-amber-500";

	autosaveTimer = setTimeout(async () => {
		try {
			saveStatusText.value = "Saving...";
			saveStatusClass.value = "text-amber-600";
			const xml = await getXml();
			emit("xml-changed", xml);
			saveStatusText.value = "Saved";
			saveStatusClass.value = "text-green-600";

			// Clear status after 3 seconds
			setTimeout(() => {
				if (saveStatusText.value === "Saved") {
					saveStatusText.value = "";
				}
			}, 3000);
		} catch (err) {
			console.error("[DmnEditor] Autosave failed:", err);
			saveStatusText.value = "Save failed";
			saveStatusClass.value = "text-red-500";
		}
	}, 2000);
}

// ── Public Methods ──────────────────────────────────────────────────
async function getXml() {
	if (!modeler) return "";
	try {
		const { xml } = await modeler.saveXML({ format: true });
		return xml;
	} catch (err) {
		console.error("[DmnEditor] saveXML failed:", err);
		return "";
	}
}

async function importXml(xml) {
	if (!modeler) return;
	try {
		await modeler.importXML(xml);
	} catch (err) {
		console.error("[DmnEditor] importXML failed:", err);
	}
}

defineExpose({ getXml, importXml });

// ── Default DMN Template ────────────────────────────────────────────
function getDefaultDmnXml() {
	return `<?xml version="1.0" encoding="UTF-8"?>
<definitions xmlns="https://www.omg.org/spec/DMN/20191111/MODEL/"
             xmlns:dmndi="https://www.omg.org/spec/DMN/20191111/DMNDI/"
             xmlns:dc="http://www.omg.org/spec/DMN/20180521/DC/"
             id="Definitions_1"
             name="Decision"
             namespace="http://camunda.org/schema/1.0/dmn">
  <decision id="Decision_1" name="Decision 1">
    <decisionTable id="DecisionTable_1" hitPolicy="UNIQUE">
      <input id="Input_1" label="Input">
        <inputExpression id="InputExpression_1" typeRef="string">
          <text></text>
        </inputExpression>
      </input>
      <output id="Output_1" label="Output" typeRef="string" />
      <rule id="Rule_1">
        <inputEntry id="InputEntry_1">
          <text></text>
        </inputEntry>
        <outputEntry id="OutputEntry_1">
          <text></text>
        </outputEntry>
      </rule>
    </decisionTable>
  </decision>
  <dmndi:DMNDI>
    <dmndi:DMNDiagram id="DMNDiagram_1">
      <dmndi:DMNShape id="DMNShape_Decision_1" dmnElementRef="Decision_1">
        <dc:Bounds height="80" width="180" x="160" y="100" />
      </dmndi:DMNShape>
    </dmndi:DMNDiagram>
  </dmndi:DMNDI>
</definitions>`;
}
</script>

<style scoped>
.dmn-editor-root {
	width: 100%;
	height: 100%;
	display: flex;
	flex-direction: column;
	background: #ffffff;
	border-radius: 0 0 8px 8px;
	overflow: hidden;
}

.dmn-container {
	flex: 1;
	min-height: 0;
	position: relative;
}

.dmn-editor-toolbar {
	user-select: none;
}
</style>
