<template>
	<div class="bpmn-editor-wrapper h-full w-full flex flex-col">
		<!-- Toolbar -->
		<div class="bpmn-toolbar flex items-center gap-2 px-3 py-2 bg-gray-50 border-b">
			<!-- Undo/Redo buttons -->
			<Tooltip text="Undo (Ctrl+Z)">
				<button
					@click="undo"
					:disabled="!canUndo"
					:class="[
						'p-2 rounded transition-colors',
						canUndo
							? 'hover:bg-gray-200 text-gray-700'
							: 'text-gray-300 cursor-not-allowed',
					]"
				>
					<Icon icon="lucide:undo-2" class="w-5 h-5" />
				</button>
			</Tooltip>
			<Tooltip text="Redo (Ctrl+Y)">
				<button
					@click="redo"
					:disabled="!canRedo"
					:class="[
						'p-2 rounded transition-colors',
						canRedo
							? 'hover:bg-gray-200 text-gray-700'
							: 'text-gray-300 cursor-not-allowed',
					]"
				>
					<Icon icon="lucide:redo-2" class="w-5 h-5" />
				</button>
			</Tooltip>

			<div class="w-px h-6 bg-gray-300 mx-1"></div>

			<!-- Delete button -->
			<Tooltip text="Delete (Del)">
				<button
					@click="deleteSelected"
					class="p-2 rounded hover:bg-gray-200 text-gray-700 transition-colors"
				>
					<Icon icon="lucide:trash-2" class="w-5 h-5" />
				</button>
			</Tooltip>

			<div class="w-px h-6 bg-gray-300 mx-1"></div>

			<!-- Formatting Toolbar -->
			<FormattingToolbar
				:selectedElements="selectedElements"
				:modeler="modelerInstance"
			/>

			<div class="flex-1"></div>

			<!-- Properties Panel Toggle -->
			<Tooltip text="Toggle Properties Panel">
				<button
					@click="togglePropertiesPanel"
					:class="[
						'p-2 rounded transition-colors',
						showPropertiesPanel
							? 'bg-gray-200 text-gray-700'
							: 'hover:bg-gray-200 text-gray-500',
					]"
				>
					<Icon icon="lucide:panel-right" class="w-5 h-5" />
				</button>
			</Tooltip>
		</div>

		<!-- Main Content Area -->
		<div class="flex-1 flex overflow-hidden">
			<!-- BPMN Canvas -->
			<div
				ref="container"
				class="bpmn-canvas flex-1"
				@dragover.prevent="handleDragOver"
				@drop.prevent="handleDrop"
			></div>

			<!-- Properties Panel -->
			<div
				v-show="showPropertiesPanel"
				ref="propertiesContainer"
				class="properties-panel-container w-80 border-l border-gray-200 bg-white overflow-auto"
			></div>
		</div>
	</div>
</template>

<script setup>
import { ref, onMounted, onUnmounted } from "vue";
import { Icon } from "@iconify/vue";
// Custom Shapes - DISABLED (see DEVELOPMENT_CONTEXT.md)
// import CustomShapesModule, { customShapeSvgStore } from "@/bpmn";
import { Tooltip } from "frappe-ui";
import FormattingToolbar from "@/components/FormattingToolbar.vue";
import { initModeler } from "@/composables/useModelerInit";
// Properties panel
import {
	BpmnPropertiesPanelModule,
	BpmnPropertiesProviderModule,
} from "bpmn-js-properties-panel";

// SpiffWorkflow extensions (ESM from forked repo)
import spiffworkflow, { spiffModdleExtension } from "bpmn-js-spiffworkflow";

// Minimap for diagram navigation - DISABLED
// import minimapModule from "diagram-js-minimap";

// i18n for translations
import translateModule from "@/i18n";

// Custom modeling rules
import customRulesModule from "@/rules";

// Custom text styling module
import { customTextStyleModule } from "@/renderers";

// Shared clipboard for cross-diagram copy/paste
import clipboardModule from "@/utils/clipboard";

// Custom moddle extension for text style attributes
import customTextStyleModdle from "@/moddle/customTextStyleModdle";

// Import bpmn-js CSS
import "bpmn-js/dist/assets/diagram-js.css";
import "bpmn-js/dist/assets/bpmn-font/css/bpmn.css";

// Import properties panel CSS
import "@bpmn-io/properties-panel/dist/assets/properties-panel.css";

const emit = defineEmits([
	"ready",
	"changed",
	"zoom-changed",
	"launch-script-editor",
	"launch-markdown-editor",
	"launch-callactivity-editor",
	"launch-callactivity-search",
]);

const container = ref(null);
const propertiesContainer = ref(null);
const canUndo = ref(false);
const canRedo = ref(false);
const zoomLevel = ref(100);
const showPropertiesPanel = ref(true);
// const showMinimap = ref(true); // DISABLED
const selectedElements = ref([]);
const modelerInstance = ref(null);
let modeler = null;
let commandStack = null;

// Empty BPMN diagram template
const emptyDiagram = `<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
                  xmlns:bpmndi="http://www.omg.org/spec/BPMN/20100524/DI"
                  xmlns:dc="http://www.omg.org/spec/DD/20100524/DC"
                  id="Definitions_1"
                  targetNamespace="http://bpmn.io/schema/bpmn">
  <bpmn:process id="Process_1" isExecutable="true">
    <bpmn:startEvent id="StartEvent_1" />
  </bpmn:process>
  <bpmndi:BPMNDiagram id="BPMNDiagram_1">
    <bpmndi:BPMNPlane id="BPMNPlane_1" bpmnElement="Process_1">
      <bpmndi:BPMNShape id="_BPMNShape_StartEvent_1" bpmnElement="StartEvent_1">
        <dc:Bounds x="173" y="102" width="36" height="36" />
      </bpmndi:BPMNShape>
    </bpmndi:BPMNPlane>
  </bpmndi:BPMNDiagram>
</bpmn:definitions>`;

function togglePropertiesPanel() {
	showPropertiesPanel.value = !showPropertiesPanel.value;
}

// toggleMinimap - DISABLED
// function toggleMinimap() {
// 	if (!modeler) return;
// 	const minimap = modeler.get("minimap");
// 	if (showMinimap.value) {
// 		minimap.close();
// 	} else {
// 		minimap.open();
// 	}
// 	showMinimap.value = !showMinimap.value;
// }

onMounted(async () => {
	await initModeler({
		container,
		propertiesContainer,
		modelerConfig: {
			additionalModules: [
				BpmnPropertiesPanelModule,
				BpmnPropertiesProviderModule,
				spiffworkflow,
				// minimapModule, // DISABLED
				translateModule,
				customTextStyleModule,
				clipboardModule,
			],
			moddleExtensions: {
				custom: customTextStyleModdle,
				spiffworkflow: spiffModdleExtension,
			},
			bpmnRenderer: {
				defaultFillColor: "#ffffff",
				defaultStrokeColor: "#1f2937",
			},
			textRenderer: {
				defaultStyle: {
					fontFamily: '"Inter", "Segoe UI", system-ui, sans-serif',
					fontSize: "12px",
				},
			},
			keyboard: { bindTo: document },
		},
		onReady: async (initializedModeler) => {
			modeler = initializedModeler;

			// Get command stack for undo/redo
			commandStack = modeler.get("commandStack");

			// Use eventBus for listening to command stack changes
			const eventBus = modeler.get("eventBus");
			eventBus.on("commandStack.changed", updateUndoRedoState);

			// Listen for selection changes for formatting toolbar
			eventBus.on("selection.changed", (e) => {
				selectedElements.value = e.newSelection || [];
			});

			// Listen for zoom changes (Ctrl+scroll, programmatic zoom, etc.)
			eventBus.on("canvas.viewbox.changed", () => {
				const canvas = modeler.get("canvas");
				const newZoom = Math.round(canvas.zoom() * 100);
				zoomLevel.value = newZoom;
				emit("zoom-changed", newZoom);
			});

			// --- SpiffWorkflow EventBus Integration ---
			eventBus.on("spiff.script.edit", (event) => {
				emit("launch-script-editor", {
					element: event.element,
					scriptType: event.scriptType,
					script: event.script || "",
					eventBus: event.eventBus,
				});
			});

			eventBus.on("spiff.markdown.edit", (event) => {
				emit("launch-markdown-editor", {
					element: event.element,
					value: event.value || "",
					eventBus: event.eventBus,
				});
			});


			eventBus.on("spiff.callactivity.edit", (event) => {
				emit("launch-callactivity-editor", {
					processId: event.processId,
					element: event.element,
				});
			});

			eventBus.on("spiff.callactivity.search", (event) => {
				emit("launch-callactivity-search", {
					processId: event.processId,
					eventBus: event.eventBus,
					element: event.element,
				});
			});

			eventBus.on("spiff.file.edit", (event) => {
				console.log("File edit requested:", event.value);
			});

			eventBus.on("spiff.dmn.edit", (event) => {
				console.log("DMN edit requested:", event.value);
			});

			eventBus.on("spiff.service_tasks.requested", (event) => {
				event.eventBus.fire("spiff.service_tasks.returned", {
					serviceTaskOperators: [],
				});
			});

			eventBus.on("spiff.json_schema_files.requested", (event) => {
				event.eventBus.fire("spiff.json_schema_files.returned", {
					options: [],
				});
			});

			eventBus.on("spiff.dmn_files.requested", (event) => {
				event.eventBus.fire("spiff.dmn_files.returned", {
					options: [],
				});
			});

			// Override Ctrl+V paste to place elements at canvas center regardless of mouse position.
			// The default bpmn-js paste uses the last mouse event position via create.start(), which
			// silently fails when the mouse was on the tab bar (not the canvas) after switching tabs.
			// Priority 2000 > default binding priority 1000, so this runs first.
			const keyboard = modeler.get("keyboard");
			const clipboardService = modeler.get("clipboard");
			const copyPaste = modeler.get("copyPaste");
			const canvasService = modeler.get("canvas");

			keyboard.addListener(2000, (context) => {
				const evt = context.keyEvent;
				const isMac = /mac/i.test(navigator.platform);
				const isPaste = (isMac ? evt.metaKey : evt.ctrlKey) && evt.key === "v";
				if (!isPaste) return;
				if (clipboardService.isEmpty()) return;

				evt.preventDefault();

				// Paste at the center of the currently visible viewport
				const viewbox = canvasService.viewbox();
				const root = canvasService.getRootElement();
				copyPaste.paste({
					element: root,
					point: {
						x: viewbox.x + viewbox.width / 2,
						y: viewbox.y + viewbox.height / 2,
					},
				});

				return false; // Prevent default bpmn-js paste handler from also running
			});


			eventBus.on("spiff.data_stores.requested", (event) => {
				event.eventBus.fire("spiff.data_stores.returned", {
					options: [],
				});
			});

			eventBus.on("spiff.messages.requested", (event) => {
				event.eventBus.fire("spiff.messages.returned", {
					configuration: { messages: [] },
				});
			});

			eventBus.on("spiff.msg_json_schema_files.requested", (event) => {
				console.log("Message JSON schema files requested");
			});

			// Fix unresolved loop data references (from upstream app.js)
			modeler.on("import.parse.complete", (event) => {
				const refs = event.references.filter(
					(r) =>
						r.property === "bpmn:loopDataInputRef" ||
						r.property === "bpmn:loopDataOutputRef"
				);
				const desc = modeler._moddle.registry.getEffectiveDescriptor(
					"bpmn:ItemAwareElement"
				);
				refs.forEach((ref) => {
					const props = {
						id: ref.id,
						name: ref.id ? typeof ref.name === "undefined" : ref.name,
					};
					const elem = modeler._moddle.create(desc, props);
					elem.$parent = ref.element;
					ref.element.set(ref.property, elem);
				});
			});

			// Expose modeler instance for child components
			modelerInstance.value = modeler;

			// Import empty diagram
			await modeler.importXML(emptyDiagram);

			emit("ready");
		},
		onError: (err) => {
			console.error("Failed to initialize BPMN modeler:", err);
		},
	});
});

onUnmounted(() => {
	if (modeler) {
		modeler.destroy();
	}
});

function updateUndoRedoState() {
	if (commandStack) {
		canUndo.value = commandStack.canUndo();
		canRedo.value = commandStack.canRedo();
	}
	emit("changed");
}

function undo() {
	if (commandStack && commandStack.canUndo()) {
		commandStack.undo();
	}
}

function redo() {
	if (commandStack && commandStack.canRedo()) {
		commandStack.redo();
	}
}

function deleteSelected() {
	if (!modeler) return;

	const selection = modeler.get("selection");
	const modeling = modeler.get("modeling");
	const selected = selection.get();

	if (selected && selected.length > 0) {
		modeling.removeElements(selected);
	}
}

// Decode HTML entities that may have been encoded during storage/retrieval
function decodeHtmlEntities(text) {
	const textarea = document.createElement("textarea");
	textarea.innerHTML = text;
	return textarea.value;
}

// Expose methods for parent component
async function getXML() {
	if (!modeler) return "";
	const { xml } = await modeler.saveXML({ format: true });
	return xml;
}

async function loadXML(xml) {
	if (!modeler) return;
	try {
		// Decode any HTML entities in the XML
		const decodedXml = decodeHtmlEntities(xml);
		await modeler.importXML(decodedXml);
		updateUndoRedoState();
		// Fit diagram to screen by default after loading
		setTimeout(() => {
			const canvas = modeler.get("canvas");
			canvas.zoom("fit-viewport");
			zoomLevel.value = Math.round(canvas.zoom() * 100);
		}, 100);
	} catch (err) {
		console.error("Failed to import XML:", err);
	}
}

function zoomIn() {
	if (!modeler) return;
	const canvas = modeler.get("canvas");
	const currentZoom = canvas.zoom();
	const newZoom = Math.min(currentZoom * 1.1, 4); // Max 400%
	canvas.zoom(newZoom);
	zoomLevel.value = Math.round(newZoom * 100);
}

function zoomOut() {
	if (!modeler) return;
	const canvas = modeler.get("canvas");
	const currentZoom = canvas.zoom();
	const newZoom = Math.max(currentZoom / 1.1, 0.1); // Min 10%
	canvas.zoom(newZoom);
	zoomLevel.value = Math.round(newZoom * 100);
}

function resetZoom() {
	if (!modeler) return;
	const canvas = modeler.get("canvas");
	canvas.zoom(1);
	zoomLevel.value = 100;
}

function fitToScreen() {
	if (!modeler) return;
	const canvas = modeler.get("canvas");
	canvas.zoom("fit-viewport");
	zoomLevel.value = Math.round(canvas.zoom() * 100);
}

function getZoomLevel() {
	return zoomLevel.value;
}

// Handle drag over for custom shapes
function handleDragOver(event) {
	event.dataTransfer.dropEffect = "copy";
}

// Handle drop of custom shape onto canvas
function handleDrop(event) {
	const dataStr = event.dataTransfer.getData("application/json");
	if (!dataStr) return;

	try {
		const shapeData = JSON.parse(dataStr);
		if (shapeData && shapeData.svg_content) {
			// Get drop position relative to canvas
			const canvas = modeler.get("canvas");
			const viewbox = canvas.viewbox();
			const containerRect = container.value.getBoundingClientRect();

			// Calculate position in diagram coordinates
			const x = viewbox.x + (event.clientX - containerRect.left) / viewbox.scale;
			const y = viewbox.y + (event.clientY - containerRect.top) / viewbox.scale;

			addCustomShape(shapeData.svg_content, x, y, shapeData.shape_name);
		}
	} catch (e) {
		console.error("Failed to parse dropped shape data:", e);
	}
}

// Add a custom shape at the specified position
function addCustomShape(svgContent, x, y, name = "Custom Shape") {
	if (!modeler) return;

	const modeling = modeler.get("modeling");
	const elementFactory = modeler.get("elementFactory");
	const canvas = modeler.get("canvas");
	const bpmnFactory = modeler.get("bpmnFactory");

	// Get the root element (process)
	const rootElement = canvas.getRootElement();

	// Create a Task business object
	const taskBo = bpmnFactory.create("bpmn:Task", {
		name: name,
	});

	// Create the shape element
	const shape = elementFactory.createShape({
		type: "bpmn:Task",
		businessObject: taskBo,
		width: 100,
		height: 80,
	});

	// Store SVG content in the global map BEFORE adding to canvas
	customShapeSvgStore.set(shape.id, svgContent);

	// Add to canvas (this triggers the renderer)
	modeling.createShape(shape, { x, y }, rootElement);
}

// Overlay API functions
function getOverlays() {
	if (!modeler) return null;
	return modeler.get("overlays");
}

function addOverlay(elementId, html, options = {}) {
	const overlays = getOverlays();
	if (!overlays) return null;
	
	const defaultOptions = {
		position: { top: -30, left: 0 },
		...options,
	};
	
	return overlays.add(elementId, {
		position: defaultOptions.position,
		html,
	});
}

function removeOverlay(overlayId) {
	const overlays = getOverlays();
	if (overlays && overlayId) {
		overlays.remove(overlayId);
	}
}

function removeOverlaysByElement(elementId) {
	const overlays = getOverlays();
	if (overlays && elementId) {
		overlays.remove({ element: elementId });
	}
}

function clearAllOverlays() {
	const overlays = getOverlays();
	if (overlays) {
		overlays.clear();
	}
}

// Element Color API functions
function setElementColor(elementIds, stroke, fill) {
	if (!modeler) return;
	const modeling = modeler.get("modeling");
	const elementRegistry = modeler.get("elementRegistry");
	
	const ids = Array.isArray(elementIds) ? elementIds : [elementIds];
	const elements = ids.map(id => elementRegistry.get(id)).filter(Boolean);
	
	if (elements.length > 0) {
		modeling.setColor(elements, { stroke, fill });
	}
}

function clearElementColor(elementIds) {
	if (!modeler) return;
	const modeling = modeler.get("modeling");
	const elementRegistry = modeler.get("elementRegistry");
	
	const ids = Array.isArray(elementIds) ? elementIds : [elementIds];
	const elements = ids.map(id => elementRegistry.get(id)).filter(Boolean);
	
	if (elements.length > 0) {
		modeling.setColor(elements, null);
	}
}

function getSelectedElements() {
	if (!modeler) return [];
	const selection = modeler.get("selection");
	return selection.get();
}

// Directly update calledElement on a Call Activity via the command stack.
// This is the reliable way to update the property regardless of SpiffWorkflow's
// async once-listener state.
function updateCalledElement(element, processId) {
	if (!modeler || !element) return;
	const cmdStack = modeler.get("commandStack");
	cmdStack.execute("element.updateProperties", {
		element,
		moddleElement: element.businessObject,
		properties: { calledElement: processId },
	});
	// Force the properties panel to re-initialize (and re-read getValue)
	// by cycling the selection. Without this the Preact TextFieldEntry
	// shows stale data until the page is refreshed.
	const selection = modeler.get("selection");
	selection.select(null);
	setTimeout(() => {
		selection.select(element);
	}, 30);
}

defineExpose({
	getXML,
	loadXML,
	undo,
	redo,
	zoomIn,
	zoomOut,
	resetZoom,
	fitToScreen,
	getZoomLevel,
	zoomLevel,
	addCustomShape,
	// Overlay API
	addOverlay,
	removeOverlay,
	removeOverlaysByElement,
	clearAllOverlays,
	// Element Color API
	setElementColor,
	clearElementColor,
	getSelectedElements,
	// Call Activity API
	updateCalledElement,
});
</script>

<style>
.bpmn-editor-wrapper {
	background: #fff;
}

.bpmn-canvas {
	background: #fafafa;
}

/* Palette Styling */
.bpmn-canvas .djs-palette {
	background: #f8f9fa;
	border-right: 1px solid #e5e7eb;
	border-radius: 0;
}

.bpmn-canvas .djs-palette .entry:hover {
	background: #e5e7eb;
}

.bpmn-canvas .djs-palette .separator {
	border-top-color: #e5e7eb;
}

/* Element Selection Styling */
.djs-element.selected .djs-outline {
	stroke: #3b82f6 !important;
	stroke-width: 2px !important;
}

.djs-element.hover .djs-outline {
	stroke: #60a5fa !important;
	stroke-width: 1.5px !important;
}

/* Context Pad Styling */
.djs-context-pad .entry:hover {
	background: #3b82f6 !important;
}

.djs-context-pad .entry:hover svg {
	fill: white;
}

/* Contain BPMN z-index values within the canvas stacking context.
   Without this, context pad (z-index:100) and popup menu (z-index:200)
   bleed through frappe-ui Dialog overlays. */
.bpmn-canvas {
	isolation: isolate;
}

/* Canvas Focus */
.bpmn-canvas:focus {
	outline: none;
}

/* Properties Panel Styling */
.properties-panel-container {
	--properties-panel-header-background-color: #f9fafb;
	--properties-panel-group-header-background-color: #f3f4f6;
	/* Contain any high z-index elements inside the panel so they don't
	   bleed above frappe-ui Dialog backdrops */
	isolation: isolate;
}

.properties-panel-container .bio-properties-panel {
	height: 100%;
}

.properties-panel-container .bio-properties-panel-header {
	background-color: #f9fafb;
	border-bottom: 1px solid #e5e7eb;
}

.properties-panel-container .bio-properties-panel-group-header {
	background-color: #f3f4f6;
}

/* Minimap Styling */
.djs-minimap {
	background: #ffffff;
	border: 1px solid #e5e7eb;
	border-radius: 8px;
	box-shadow: 0 4px 6px -1px rgb(0 0 0 / 0.1);
}

.djs-minimap .map {
	border-radius: 6px;
}

.djs-minimap .viewport {
	border: 2px solid #3b82f6;
	background: rgba(59, 130, 246, 0.1);
}

/* Overlay Styling */
.bpmn-overlay {
	padding: 4px 8px;
	border-radius: 4px;
	font-size: 12px;
	font-weight: 500;
	white-space: nowrap;
	pointer-events: auto;
	cursor: pointer;
}

.bpmn-overlay-error {
	background: #ef4444;
	color: white;
}

.bpmn-overlay-warning {
	background: #f59e0b;
	color: white;
}

.bpmn-overlay-info {
	background: #3b82f6;
	color: white;
}

.bpmn-overlay-success {
	background: #10b981;
	color: white;
}

.bpmn-overlay-badge {
	display: inline-flex;
	align-items: center;
	justify-content: center;
	min-width: 20px;
	height: 20px;
	border-radius: 10px;
	font-size: 11px;
	font-weight: 600;
}
</style>
