<template>
	<div class="bpmn-editor-wrapper h-full w-full flex flex-col">
		<!-- Toolbar (moved natively to parent Editor.vue's header) -->
		<div ref="toolbarEl" v-show="isMounted" class="flex items-center gap-1.5 w-full h-full text-gray-700">
			<template v-if="!readonly">
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

				<!-- Sticky Note button -->
				<button
					@click="addStickyNote"
					title="Add Sticky Note"
					class="p-1.5 flex items-center justify-center rounded hover:bg-gray-100 text-gray-700 transition-colors"
				>
					<Icon icon="lucide:sticky-note" class="w-4 h-4" />
				</button>

				<div class="w-px h-5 bg-gray-200 mx-1 shrink-0"></div>

				<!-- Formatting Toolbar -->
				<FormattingToolbar
					:selectedElements="selectedElements"
					:modeler="modelerInstance"
					class="shrink-0"
				/>
			</template>

			<!-- Read-only indicator -->
			<div v-if="readonly" class="flex items-center gap-1.5 text-gray-400 text-sm">
				<Icon icon="lucide:lock" class="w-4 h-4" />
				<span>View Only</span>
			</div>


			<!-- Save Status Indicator before Properties Panel Toggle -->
			<div class="flex-1 min-w-4 flex items-center justify-end px-3">
				<div v-if="saveStatusText && !readonly" class="text-sm font-medium transition-colors mr-2" :class="saveStatusColor">
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
				:class="['bpmn-canvas flex-1', { 'bpmn-canvas--readonly': readonly }]"
				@dragover.prevent="!readonly && handleDragOver($event)"
				@drop.prevent="!readonly && handleDrop($event)"
			></div>

			<!-- Properties Panel -->
			<div
				v-show="showPropertiesPanel"
				ref="propertiesContainer"
				:class="['properties-panel-container w-96 border-l border-gray-200 bg-white overflow-auto', { 'properties-panel--readonly': readonly }]"
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
import { customTextStyleModule, stickyNoteModule } from "@/renderers";

// Native system-clipboard module — enables copy/paste across browser tabs.
// Inlined from https://github.com/nikku/bpmn-js-native-copy-paste (MIT)
// because the npm package requires bpmn-js >= 18 (project uses 17).
import nativeCopyPasteModule from "@/utils/nativeCopyPaste";
import clipboardModule from "@/utils/clipboard";

// Custom moddle extension for text style attributes
import customTextStyleModdle from "@/moddle/customTextStyleModdle";

// Task resize + auto-label-fit module
import resizeModule from "@/resize";

import userTaskPropertiesProviderModule from "@/bpmn/userTaskPropertiesProvider";
import sendTaskPropertiesProviderModule from "@/bpmn/sendTaskPropertiesProvider";
import intermediateEventPropertiesProviderModule from "@/bpmn/intermediateEventPropertiesProvider";
import timerPropertiesProviderModule from "@/bpmn/timerPropertiesProvider";
import startEventPropertiesProviderModule from "@/bpmn/startEventPropertiesProvider";
import conditionalStartEventPropertiesProviderModule from "@/bpmn/conditionalStartEventPropertiesProvider";
import propertiesPanelFilterModule from "@/bpmn/propertiesPanelFilter";

// bpmnlint — diagram validation
import lintModule from "bpmn-js-bpmnlint";
import "bpmn-js-bpmnlint/dist/assets/css/bpmn-js-bpmnlint.css";
import bpmnlintConfig from "@/linting/bpmnlintrc.js";

// Import bpmn-js CSS
import "bpmn-js/dist/assets/diagram-js.css";
import "bpmn-js/dist/assets/bpmn-js.css";
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
	},
	readonly: {
		type: Boolean,
		default: false
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
	"launch-notification-editor",
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

			// Conditional Start Event trigger extension (hot-reloading safety)
			const hasCondStartEventExt = spiffModdleExtension.types.find(t => t.name === "ConditionalEventTriggerExtension");
			if (!hasCondStartEventExt) {
				spiffModdleExtension.types.push({
					name: "ConditionalEventTriggerExtension",
					extends: ["bpmn:ConditionalEventDefinition"],
					properties: [
						{ name: "triggerDoctype",       isAttr: true, type: "String" },
						{ name: "triggerType",          isAttr: true, type: "String" },
						{ name: "triggerWorkflow",      isAttr: true, type: "String" },
						{ name: "triggerWorkflowState", isAttr: true, type: "String" }
					]
				});
			}

			// User Task assignee extension
			const hasUserTaskExt = spiffModdleExtension.types.find(t => t.name === "UserTaskAssigneeExtension");
			if (!hasUserTaskExt) {
				spiffModdleExtension.types.push({
					name: "UserTaskAssigneeExtension",
					extends: ["bpmn:UserTask"],
					properties: [
						{ name: "assigneeMode",        isAttr: true, type: "String" },
						{ name: "targetDoctype",       isAttr: true, type: "String" },
						{ name: "assigneeUser",        isAttr: true, type: "String" },
						{ name: "assigneeDocfield",    isAttr: true, type: "String" }
					]
				});
			}
			
			// Intermediate Event extension (hot-reloading safety)
			const hasIntermediateEventExt = spiffModdleExtension.types.find(t => t.name === "IntermediateEventExtension");
			if (!hasIntermediateEventExt) {
				spiffModdleExtension.types.push({
					name: "IntermediateEventExtension",
					extends: ["bpmn:IntermediateCatchEvent", "bpmn:IntermediateThrowEvent"],
					properties: [
						{ name: "targetDoctype", isAttr: true, type: "String" },
						{ name: "triggerWorkflow", isAttr: true, type: "String" },
						{ name: "triggerWorkflowState", isAttr: true, type: "String" },
						{ name: "assignmentRule", isAttr: true, type: "String" }
					]
				});
			}

			// Send Task notification extension
			const hasSendTaskExt = spiffModdleExtension.types.find(t => t.name === "SendTaskNotificationExtension");
			if (!hasSendTaskExt) {
				spiffModdleExtension.types.push({
					name: "SendTaskNotificationExtension",
					extends: ["bpmn:SendTask"],
					properties: [
						{ name: "notificationName", isAttr: true, type: "String" }
					]
				});
			}

			// Sticky Note extension
			const hasStickyNoteExt = spiffModdleExtension.types.find(t => t.name === "StickyNoteExtension");
			if (!hasStickyNoteExt) {
				spiffModdleExtension.types.push({
					name: "StickyNoteExtension",
					extends: ["bpmn:TextAnnotation"],
					properties: [
						{ name: "isStickyNote", isAttr: true, type: "Boolean" },
						{ name: "color", isAttr: true, type: "String" }
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
				userTaskPropertiesProviderModule,
				sendTaskPropertiesProviderModule,
				intermediateEventPropertiesProviderModule,
				timerPropertiesProviderModule,
				startEventPropertiesProviderModule,
				conditionalStartEventPropertiesProviderModule,
				// minimapModule, // DISABLED
				translateModule,
				customTextStyleModule,
				resizeModule,
				stickyNoteModule,
				clipboardModule,
				lintModule,
				nativeCopyPasteModule,
				propertiesPanelFilterModule,
			],
			taskResizingEnabled: true,
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
			// Disable keyboard bindings in readonly mode to prevent
			// delete/move/copy keyboard shortcuts from modifying the diagram
			keyboard: props.readonly ? false : { bindTo: document },
		},
		onReady: async (initializedModeler) => {
			modeler = initializedModeler;

			// Get command stack for undo/redo
			commandStack = modeler.get("commandStack");

			// Use eventBus for listening to command stack changes
			const eventBus = modeler.get("eventBus");


			// Clear custom trigger attributes if a StartEvent is converted into something else
			// (e.g. Timer Start Event) so they don't persist in the XML.
			// Use modeling.updateModdleProperties so the operation is tracked by the command
			// stack and is properly undoable/redoable.
			eventBus.on("commandStack.shape.replace.postExecute", (e) => {
				const newShape = e.context.newShape;
				const bo = newShape && newShape.businessObject;
				if (!bo) return;

				const modeling = modeler.get("modeling");
				const triggerAttrs = ["triggerDoctype", "triggerType", "triggerWorkflow", "triggerWorkflowState"];
				const clearProps = {};
				triggerAttrs.forEach(attr => {
					clearProps[`spiffworkflow:${attr}`] = undefined;
				});

				if (bo.$type === "bpmn:StartEvent") {
					const eventDefs = bo.get("eventDefinitions") || [];
					const isPlainStartEvent = eventDefs.length === 0;
					const hasConditionalDef = eventDefs.some(d => d.$type === "bpmn:ConditionalEventDefinition");

					// Clear trigger attrs from the StartEvent BO if it's no longer plain
					if (!isPlainStartEvent) {
						modeling.updateModdleProperties(newShape, bo, clearProps);
					}

					// Clear trigger attrs from ConditionalEventDefinition if the shape
					// was converted away from a Conditional Start Event
					if (!hasConditionalDef) {
						// Check the old shape's event defs for stale conditional data
						const oldShape = e.context.oldShape;
						const oldBo = oldShape && oldShape.businessObject;
						if (oldBo) {
							const oldDefs = oldBo.get("eventDefinitions") || [];
							const oldCondDef = oldDefs.find(d => d.$type === "bpmn:ConditionalEventDefinition");
							if (oldCondDef) {
								modeling.updateModdleProperties(newShape, oldCondDef, clearProps);
							}
						}
					}
				} else {
					// Not a StartEvent at all — clear any lingering trigger attrs
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

			// Notification editing (Send Tasks)
			eventBus.on("spiff.notification.edit", (event) => {
				emit("launch-notification-editor", {
					element: event.element,
					notificationName: event.notificationName || "",
					eventBus: event.eventBus,
				});
			});

			// Write notification name back to BPMN element when dialog resolves
			eventBus.on("spiff.notification.update", (event) => {
				if (event.element && event.notificationName) {
					const modeling = modeler.get("modeling");
					const bo = event.element.businessObject || event.element;
					modeling.updateModdleProperties(event.element, bo, {
						"spiffworkflow:notificationName": event.notificationName,
					});
				}
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
				const refs = (event.references || []).filter(
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



			// In readonly mode, disable all modeler-level editing interactions
			// so users cannot move, delete, or modify elements locally.
			if (props.readonly) {
				// Intercept commandStack to prevent any model mutations
				const originalExecute = commandStack.execute.bind(commandStack);
				commandStack.execute = (command, context) => {
					// Allow canvas operations (zoom, scroll) but block element mutations
					const allowedCommands = ['canvas.updateRootElement'];
					if (allowedCommands.includes(command)) {
						return originalExecute(command, context);
					}
					// Silently ignore all other commands
					return;
				};

				// Disable direct editing (double-click labels)
				try {
					const directEditing = modeler.get('directEditing');
					if (directEditing) {
						directEditing.cancel();
						const origActivate = directEditing.activate;
						directEditing.activate = () => false;
					}
				} catch (_) { /* module may not exist */ }

				// Disable dragging
				try {
					const dragging = modeler.get('dragging');
					if (dragging) {
						const origInit = dragging.init;
						dragging.init = () => {};
					}
				} catch (_) { /* module may not exist */ }
			}

			emit("ready");
		},
		onError: (err) => {
			console.error("Failed to initialize BPMN modeler:", err);
		},
		
	});
	} catch (err) {
		console.error("Error in onMounted initialized setup:", err);
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
	// Suppress change events in readonly mode so auto-save doesn't fire
	if (!isImporting.value && !props.readonly) {
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
	if (!modelerInstance.value) return;

	const modeler = modelerInstance.value;
	const selection = modeler.get("selection");
	const modeling = modeler.get("modeling");
	const selected = selection.get();

	if (selected && selected.length > 0) {
		modeling.removeElements(selected);
	}
}

function addStickyNote() {
	if (!modelerInstance.value) return;

	const modeler = modelerInstance.value;
	const modeling = modeler.get("modeling");
	const canvas = modeler.get("canvas");
	const bpmnFactory = modeler.get("bpmnFactory");
	const elementFactory = modeler.get("elementFactory");

	const rootElement = canvas.getRootElement();

	// Create TextAnnotation business object
	const textAnnotationBo = bpmnFactory.create("bpmn:TextAnnotation", {
		text: "New Note",
	});

	// Set the custom attribute within the spiffworkflow namespace
	textAnnotationBo.set("spiffworkflow:isStickyNote", true);
	textAnnotationBo.set("spiffworkflow:color", "#fff9c4"); // Default pastel yellow

	// Get viewport center
	const viewbox = canvas.viewbox();
	const x = viewbox.x + viewbox.width / 2;
	const y = viewbox.y + viewbox.height / 2;

	const shape = elementFactory.createShape({
		type: "bpmn:TextAnnotation",
		businessObject: textAnnotationBo,
		width: 150,
		height: 120,
	});

	modeling.createShape(shape, { x, y }, rootElement);
	
	// Select the new shape and activate direct editing
	const selection = modeler.get("selection");
	selection.select(shape);
	
	const directEditing = modeler.get("directEditing");
	// Small delay to ensure the SVG is rendered before activating editor
	setTimeout(() => {
		if (directEditing.canActivate(shape)) {
			directEditing.activate(shape);
		}
	}, 100);
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

/* Launch Editor Button Styling */
.properties-panel-container .spiffworkflow-properties-panel-button {
	display: inline-flex;
	align-items: center;
	gap: 6px;
	padding: 6px 14px;
	margin: 4px 8px 8px;
	font-size: 12px;
	font-weight: 500;
	color: #374151;
	background: #f3f4f6;
	border: 1px solid #d1d5db;
	border-radius: 6px;
	cursor: pointer;
	transition: all 0.15s ease;
	box-shadow: 0 1px 2px rgba(0, 0, 0, 0.05);
}

.properties-panel-container .spiffworkflow-properties-panel-button:hover {
	background: #e5e7eb;
	border-color: #9ca3af;
	box-shadow: 0 1px 3px rgba(0, 0, 0, 0.1);
}

.properties-panel-container .spiffworkflow-properties-panel-button:active {
	background: #d1d5db;
	box-shadow: inset 0 1px 2px rgba(0, 0, 0, 0.1);
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

/* Properties Panel Styling (Frappe UI Skin) */
.properties-panel-container {
	--properties-panel-header-background-color: #f9fafb;
	--properties-panel-group-header-background-color: #f3f4f6;
	background-color: #ffffff;
	border-left: 1px solid #e5e7eb;
	font-family: 'Inter', system-ui, sans-serif;
	isolation: isolate;
}

.properties-panel-container .bio-properties-panel {
	height: 100%;
}

.properties-panel-container .bio-properties-panel-header {
	background-color: #f9fafb;
	border-bottom: 1px solid #e5e7eb;
	padding: 12px 16px;
}

.properties-panel-container .bio-properties-panel-header-title {
	font-size: 14px;
	font-weight: 700;
	color: #1f2937;
}

.properties-panel-container .bio-properties-panel-group-header {
	background-color: #f3f4f6;
	border-bottom: 1px solid #e5e7eb;
	padding: 8px 16px;
	transition: background-color 0.2s ease;
}

.properties-panel-container .bio-properties-panel-group-header:hover {
	background-color: #e5e7eb;
}

.properties-panel-container .bio-properties-panel-group-header-title {
	font-size: 11px;
	font-weight: 700;
	color: #4b5563;
	text-transform: uppercase;
	letter-spacing: 0.05em;
}

/* Form Controls */
.properties-panel-container .bio-properties-panel-label {
	display: block;
	font-size: 12px;
	font-weight: 500;
	color: #4b5563;
	margin-bottom: 6px;
	margin-top: 12px;
}

.properties-panel-container .bio-properties-panel-input,
.properties-panel-container .bio-properties-panel-select,
.properties-panel-container .bio-properties-panel-textarea {
	width: 100%;
	background-color: #f9fafb;
	border: 1px solid #d1d5db;
	border-radius: 6px;
	padding: 6px 10px;
	font-size: 13px;
	color: #1f2937;
	transition: all 0.2s ease;
	box-shadow: 0 1px 2px rgba(0, 0, 0, 0.05);
}

.properties-panel-container .bio-properties-panel-input:focus,
.properties-panel-container .bio-properties-panel-select:focus,
.properties-panel-container .bio-properties-panel-textarea:focus {
	outline: none;
	background-color: #ffffff;
	border-color: #3b82f6;
	box-shadow: 0 0 0 2px rgba(59, 130, 246, 0.1);
}

.properties-panel-container .bio-properties-panel-input::placeholder {
	color: #9ca3af;
}

/* Checkbox Styling */
.properties-panel-container .bio-properties-panel-checkbox {
	width: 16px;
	height: 16px;
	border-radius: 4px;
	border: 1px solid #d1d5db;
	cursor: pointer;
}

/* Group Entries */
.properties-panel-container .bio-properties-panel-entry {
	padding: 8px 16px;
}

.properties-panel-container .bio-properties-panel-group-entries {
	border-bottom: 1px solid #f3f4f6;
	padding-bottom: 8px;
}

/* Frequency Explanation Card (Timer Start Event) */
.properties-panel-container .frequency-explanation {
	padding: 6px 10px;
}

.properties-panel-container .frequency-explanation__card {
	background: var(--properties-panel-group-header-background-color, #f3f4f6);
	border-radius: 6px;
	padding: 12px;
	font-size: 12.5px;
	line-height: 1.6;
	color: #374151;
}

.properties-panel-container .frequency-explanation__title {
	font-weight: 600;
	font-size: 13px;
	margin-bottom: 8px;
	color: #111827;
}

.properties-panel-container .frequency-explanation__desc {
	margin-bottom: 8px;
}

.properties-panel-container .frequency-explanation__label {
	font-weight: 600;
	color: #111827;
}

.properties-panel-container .frequency-explanation__note {
	font-size: 11.5px;
	color: #6b7280;
	font-style: italic;
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

/* ── Breadcrumb Navigation (collapsed subprocess drilldown) ── */
.bpmn-canvas .bjs-breadcrumbs {
	font-family: 'Inter', 'Segoe UI', system-ui, sans-serif;
	font-size: 14px;
	z-index: 10;
}

.bpmn-canvas .bjs-breadcrumbs li a {
	color: #3b82f6;
	text-decoration: none;
	transition: color 0.15s ease;
}

.bpmn-canvas .bjs-breadcrumbs li a:hover {
	color: #2563eb;
	text-decoration: underline;
}

.bpmn-canvas .bjs-breadcrumbs li:last-of-type a {
	color: #374151;
	font-weight: 500;
}

/* ── Read-Only Mode ─────────────────────────────── */

/* Hide palette and context pad in read-only mode */
.bpmn-canvas--readonly .djs-palette,
.bpmn-canvas--readonly .djs-context-pad,
.bpmn-canvas--readonly .djs-popup,
.bpmn-canvas--readonly .djs-direct-editing-parent {
	display: none !important;
}

/* Disable drag/move cursor on elements in read-only mode */
.bpmn-canvas--readonly .djs-element {
	cursor: default !important;
}

/* Semi-transparent overlay to visually indicate read-only */
.bpmn-canvas--readonly {
	position: relative;
}

.bpmn-canvas--readonly::after {
	content: '';
	position: absolute;
	inset: 0;
	background: rgba(248, 250, 252, 0.15);
	pointer-events: none;
	z-index: 1;
}

/* Make properties panel inputs read-only */
.properties-panel--readonly input,
.properties-panel--readonly textarea,
.properties-panel--readonly select,
.properties-panel--readonly button {
	pointer-events: none !important;
	opacity: 0.7;
}

/* But keep the panel header and group headers interactive for collapsing */
.properties-panel--readonly .bio-properties-panel-group-header {
	pointer-events: auto !important;
	opacity: 1;
}

.properties-panel--readonly .bio-properties-panel-header {
	pointer-events: auto !important;
	opacity: 1;
}
/* ─────────────────────────────────────────────────── */

/* Sticky Note Direct Editing Fix:
   These styles apply to the bpmn-js direct editing text box.
   We force the background and text color to match the sticky note
   aesthetics during the active edit phase. */
.bpmn-canvas .djs-direct-editing-parent {
	background-color: #fff9c4 !important; /* Pastel yellow */
	border: 1px solid #eab308 !important;   /* yellow-500 border */
	border-radius: 2px;
	padding: 4px;
	box-shadow: 0 2px 4px rgba(0,0,0,0.1);
}

.bpmn-canvas .djs-direct-editing-content {
	color: #000000 !important;             /* Black text */
	font-family: 'Inter', 'Segoe UI', system-ui, sans-serif !important;
	font-size: 13px !important;
	line-height: 1.2 !important;
	outline: none !important;
}

/* Ensure placeholder/empty state is legible */
.bpmn-canvas .djs-direct-editing-content:empty:before {
	color: rgba(0,0,0,0.3);
}
</style>
