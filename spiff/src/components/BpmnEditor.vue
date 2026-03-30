<template>
	<div class="bpmn-editor-wrapper h-full w-full flex flex-col">
		<!-- Toolbar (moved natively to parent Editor.vue's header) -->
		<div ref="toolbarEl" v-show="isMounted" class="flex items-center gap-1.5 w-full h-full text-gray-700">
			<!-- Undo/Redo buttons -->
			<button
				@click="undo"
				title="Undo (Ctrl+Z)"
				:disabled="!canUndo"
				:class="[
					'p-1.5 flex items-center justify-center rounded transition-colors',
					canUndo
						? 'hover:bg-gray-100 text-gray-700'
						: 'text-gray-300 cursor-not-allowed',
				]"
			>
				<Icon icon="lucide:undo-2" class="w-4 h-4" />
			</button>
			<button
				@click="redo"
				title="Redo (Ctrl+Y)"
				:disabled="!canRedo"
				:class="[
					'p-1.5 flex items-center justify-center rounded transition-colors',
					canRedo
						? 'hover:bg-gray-100 text-gray-700'
						: 'text-gray-300 cursor-not-allowed',
				]"
			>
				<Icon icon="lucide:redo-2" class="w-4 h-4" />
			</button>

			<div class="w-px h-5 bg-gray-200 mx-1 shrink-0"></div>

			<!-- Delete button -->
			<button
				@click="deleteSelected"
				title="Delete (Del)"
				class="p-1.5 flex items-center justify-center rounded hover:bg-gray-100 text-gray-700 transition-colors"
			>
				<Icon icon="lucide:trash-2" class="w-4 h-4" />
			</button>

			<div class="w-px h-5 bg-gray-200 mx-1 shrink-0"></div>

			<!-- Formatting Toolbar -->
			<FormattingToolbar
				:selectedElements="selectedElements"
				:modeler="modelerInstance"
				class="shrink-0"
			/>


			<!-- Save Status Indicator before Properties Panel Toggle -->
			<div class="flex-1 min-w-4 flex items-center justify-end px-3">
				<div v-if="saveStatusText" class="text-sm font-medium transition-colors mr-2" :class="saveStatusColor">
					{{ saveStatusText }}
				</div>
			</div>
			
			<div class="shrink-0 pl-1 border-l border-gray-200">
				<button
					@click="togglePropertiesPanel"
					title="Toggle Properties Panel"
					:class="[
						'p-1.5 flex items-center justify-center rounded transition-colors',
						showPropertiesPanel
							? 'bg-gray-200 text-gray-800 shadow-[inset_0_1px_2px_rgba(0,0,0,0.1)]'
							: 'hover:bg-gray-100 text-gray-600',
					]"
				>
					<Icon icon="lucide:panel-right" class="w-4 h-4" />
				</button>
			</div>
		</div>



		<!-- Main Content Area -->
		<div class="flex-1 flex overflow-hidden relative">
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
import { ref, shallowRef, onMounted, onUnmounted, onBeforeUnmount } from "vue";
import {
	injectProcessNameField,
	reinjectIfCalledElementChanged,
	removeProcessNameField,
	cancelPendingInjection,
} from "@/composables/useCallActivityName";
import { Icon } from "@iconify/vue";
// Custom Shapes - DISABLED (see DEVELOPMENT_CONTEXT.md)
// import CustomShapesModule, { customShapeSvgStore } from "@/bpmn";
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

// Native system-clipboard module — enables copy/paste across browser tabs.
// Inlined from https://github.com/nikku/bpmn-js-native-copy-paste (MIT)
// because the npm package requires bpmn-js >= 18 (project uses 17).
import nativeCopyPasteModule from "@/utils/nativeCopyPaste";

// Custom moddle extension for text style attributes
import customTextStyleModdle from "@/moddle/customTextStyleModdle";

import timerPropertiesProviderModule from "@/bpmn/timerPropertiesProvider";
import startEventPropertiesProviderModule from "@/bpmn/startEventPropertiesProvider";

// bpmnlint — diagram validation
import lintModule from "bpmn-js-bpmnlint";
import "bpmn-js-bpmnlint/dist/assets/css/bpmn-js-bpmnlint.css";
import bpmnlintConfig from "@/linting/bpmnlintrc.js";

// Import bpmn-js CSS
import "bpmn-js/dist/assets/diagram-js.css";
import "bpmn-js/dist/assets/bpmn-font/css/bpmn.css";

// Import properties panel CSS
import "@bpmn-io/properties-panel/dist/assets/properties-panel.css";

const props = defineProps({
	saveStatusText: {
		type: String,
		default: ""
	},
	saveStatusColor: {
		type: String,
		default: ""
	}
});

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
const toolbarEl = ref(null);
const canUndo = ref(false);
const canRedo = ref(false);
const zoomLevel = ref(100);
const showPropertiesPanel = ref(true);
const isMounted = ref(false);
const isImporting = ref(false);
// const showMinimap = ref(true); // DISABLED
const selectedElements = shallowRef([]);
const modelerInstance = shallowRef(null);

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
	isMounted.value = true;
	try {
		// Extend spiff workflow moddle definitions to include our custom timer properties
		if (spiffModdleExtension && Array.isArray(spiffModdleExtension.types)) {
			// Timer extension (hot-reloading safety)
			const hasTimerExt = spiffModdleExtension.types.find(t => t.name === "TimerEventDefinitionExtension");
			if (!hasTimerExt) {
				spiffModdleExtension.types.push({
					name: "TimerEventDefinitionExtension",
					extends: ["bpmn:TimerEventDefinition"],
					properties: [
						{ name: "schedulerFrequency", isAttr: true, type: "String" },
						{ name: "cronExpression",       isAttr: true, type: "String" }
					]
				});
			}

			// Start Event trigger extension (hot-reloading safety)
			const hasStartEventExt = spiffModdleExtension.types.find(t => t.name === "StartEventTriggerExtension");
			if (!hasStartEventExt) {
				spiffModdleExtension.types.push({
					name: "StartEventTriggerExtension",
					extends: ["bpmn:StartEvent"],
					properties: [
						{ name: "triggerDoctype",      isAttr: true, type: "String" },
						{ name: "triggerType",         isAttr: true, type: "String" },
						{ name: "triggerWorkflow",     isAttr: true, type: "String" },
						{ name: "triggerWorkflowState",isAttr: true, type: "String" }
					]
				});
			}
		}

				
	await initModeler({
		container,
		propertiesContainer,
		modelerConfig: {
			additionalModules: [
				BpmnPropertiesPanelModule,
				BpmnPropertiesProviderModule,
				spiffworkflow,
				timerPropertiesProviderModule,
				startEventPropertiesProviderModule,
				// minimapModule, // DISABLED
				translateModule,
				customTextStyleModule,
				clipboardModule,
				lintModule,
				nativeCopyPasteModule,
			],
			linting: {
				active: true,
				bpmnlint: bpmnlintConfig,
			},
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


		// Clear custom trigger attributes if a StartEvent is converted into something else
		// (e.g. Timer Start Event) so they don't persist in the XML.
		// Use modeling.updateModdleProperties so the operation is tracked by the command
		// stack and is properly undoable/redoable.
		eventBus.on("commandStack.shape.replace.postExecute", (e) => {
			const newShape = e.context.newShape;
			const bo = newShape && newShape.businessObject;
			if (!bo) return;

			let isPlainStartEvent = false;
			if (bo.$type === "bpmn:StartEvent") {
				const eventDefs = bo.get("eventDefinitions") || [];
				isPlainStartEvent = eventDefs.length === 0;
			}


			// Clear custom trigger attributes if a StartEvent is converted into something else
			// (e.g. Timer Start Event) so they don't persist in the XML.
			// Use modeling.updateModdleProperties so the operation is tracked by the command
			// stack and is properly undoable/redoable.
			eventBus.on("commandStack.shape.replace.postExecute", (e) => {
				const newShape = e.context.newShape;
				const bo = newShape && newShape.businessObject;
				if (!bo) return;

				let isPlainStartEvent = false;
				if (bo.$type === "bpmn:StartEvent") {
					const eventDefs = bo.get("eventDefinitions") || [];
					isPlainStartEvent = eventDefs.length === 0;
				}

				if (!isPlainStartEvent) {
					const modeling = modeler.get("modeling");
					const attrs = ["triggerDoctype", "triggerType", "triggerWorkflow", "triggerWorkflowState"];
					const clearProps = {};
					attrs.forEach(attr => {
						clearProps[`spiffworkflow:${attr}`] = undefined;
					});
					modeling.updateModdleProperties(newShape, bo, clearProps);
				}
			});


			// Listen for selection changes for formatting toolbar
			eventBus.on("selection.changed", (e) => {
				selectedElements.value = e.newSelection || [];

				// Inject Process Name field when a Call Activity is selected
				const single = e.newSelection?.length === 1 ? e.newSelection[0] : null;
				if (single?.type === "bpmn:CallActivity") {
					injectProcessNameField(single, propertiesContainer);
				} else {
					// Cancel any in-flight resolve before removing the field
					cancelPendingInjection();
					removeProcessNameField(propertiesContainer);
				}
			});

			// Re-inject only when calledElement actually changed — avoids DOM
			// churn and repeated network requests on every command stack event.
			eventBus.on("commandStack.changed", () => {
				updateUndoRedoState();
				const selection = modeler.get("selection");
				const selected = selection.get();
				if (selected?.length === 1 && selected[0]?.type === "bpmn:CallActivity") {
					reinjectIfCalledElementChanged(selected[0], propertiesContainer);
				}
			});

		// Listen for zoom changes (Ctrl+scroll, programmatic zoom, etc.)
		eventBus.on("canvas.viewbox.changed", () => {
			const canvas = modeler.get("canvas");
			const newZoom = Math.round(canvas.zoom() * 100);
			zoomLevel.value = newZoom;
			emit("zoom-changed", newZoom);
		});

		// --- SpiffWorkflow EventBus Integration ---
		// These handlers are required for the spiffworkflow properties panel
		// "Launch Editor" buttons and data-request dropdowns to function.

		// Script editing (Script Tasks, Pre/Post scripts)
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

			// nativeCopyPasteModule fires 'native-copy-paste:error' on any
			// clipboard API failure (unavailable, permission denied, or parse
			// error). Log it here so it surfaces in the browser console.
			eventBus.on("native-copy-paste:error", ({ message, error }) => {
				console.warn("[native-copy-paste]", message, error);
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

			// Append toolbar natively to top header
			isMounted.value = true;
			const targetToolbar = document.getElementById("bpmn-editor-toolbar");
			if (targetToolbar && toolbarEl.value) {
				targetToolbar.innerHTML = '';
				targetToolbar.appendChild(toolbarEl.value);
			}



			emit("ready");
		},
		onError: (err) => {
			console.error("Failed to initialize BPMN modeler:", err);
		},
		
	});
} catch (err) {
		console.error("Failed to initialize BPMN modeler:", err);
	}
});

onBeforeUnmount(() => {
	isMounted.value = false;
	// Safely clean up native DOM mounting
	if (toolbarEl.value && toolbarEl.value.parentNode) {
		toolbarEl.value.parentNode.removeChild(toolbarEl.value);
	}
});

onUnmounted(() => {
	// Cancel any pending process-name injection to prevent memory-leaks
	// and stale DOM updates after the component is torn down.
	cancelPendingInjection();
	if (modeler) {
		modeler.destroy();
	}
});

function updateUndoRedoState() {
	if (commandStack) {
		canUndo.value = commandStack.canUndo();
		canRedo.value = commandStack.canRedo();
	}
	if (!isImporting.value) {
		emit("changed");
	}
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
	isImporting.value = true;
	try {
		// Decode any HTML entities in the XML
		const decodedXml = decodeHtmlEntities(xml);
		await modeler.importXML(decodedXml);
		updateUndoRedoState();
		// Fit diagram to screen by default after loading, safely catching zero-dimension errors
		setTimeout(() => {
			try {
				const canvas = modeler.get("canvas");
				canvas.zoom("fit-viewport");
				zoomLevel.value = Math.round(canvas.zoom() * 100);
			} catch (e) {
				console.warn("Could not fit viewport automatically - container may be hidden:", e);
			}
		}, 100);
	} catch (err) {
		console.error("Failed to import XML:", err);
	} finally {
		isImporting.value = false;
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

// ── Process Name DOM injection ──────────────────────────────────────────────
// Injection logic (stale-timer guard, frappeRequest, calledElement cache) has
// been extracted to @/composables/useCallActivityName.js.
// BpmnEditor only wires the eventBus events and passes the propertiesContainer ref.
// ────────────────────────────────────────────────────────────────────────────

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

/* ── Injected Process Name field (no inline styles) ─── */
.bpmn-process-name-value {
	display: flex;
	align-items: center;
	min-height: 28px;
	padding: 2px 8px;
	font-size: 12px;
	color: var(--gray-900, #111827);
	background: var(--gray-50, #f9fafb);
	border: 1px solid var(--gray-200, #e5e7eb);
	border-radius: 4px;
	word-break: break-word;
}

.bpmn-process-name-resolving {
	color: var(--gray-400, #9ca3af);
	font-style: italic;
}

.bpmn-process-name-empty {
	color: var(--gray-400, #9ca3af);
	font-style: italic;
}
/* ─────────────────────────────────────────────────── */

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
