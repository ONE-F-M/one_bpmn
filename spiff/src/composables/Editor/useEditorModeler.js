import { onBeforeUnmount, onMounted } from "vue";
import { cancelPendingInjection } from "@/composables/useCallActivityName";
import { initModeler } from "@/composables/useModelerInit";
import { BpmnPropertiesPanelModule, BpmnPropertiesProviderModule } from "bpmn-js-properties-panel";
import spiffworkflow, { spiffModdleExtension } from "bpmn-js-spiffworkflow";
import translateModule from "@/bpmn/aiAgentTranslate";
import { customTextStyleModule, serviceTaskIconModule, stickyNoteModule } from "@/bpmn/renderers";
import customTextStyleModdle from "@/bpmn/moddle/customTextStyleModdle";
import resizeModule from "@/bpmn/resize";
import userTaskPropertiesProviderModule from "@/bpmn/userTaskPropertiesProvider";
import sendTaskPropertiesProviderModule from "@/bpmn/sendTaskPropertiesProvider/SendTaskPropertiesProvider";
import serviceTaskPropertiesProviderModule from "@/bpmn/serviceTaskPropertiesProvider/ServiceTaskPropertiesProvider";
import aiAgentPropertiesProviderModule from "@/bpmn/aiAgentPropertiesProvider/AiAgentPropertiesProvider";
import aiAgentReplaceMenuProviderModule from "@/bpmn/aiAgentReplaceMenuProvider";
import aiAgentRendererModule from "@/bpmn/aiAgentRenderer";
import adhocSubprocessPropertiesProviderModule from "@/bpmn/adhocSubprocessPropertiesProvider/AdhocSubprocessPropertiesProvider";
import aiTaskSelectorMenuProviderModule from "@/bpmn/aiTaskSelectorMenuProvider";
import aiTaskSelectorPropertiesProviderModule from "@/bpmn/aiTaskSelectorPropertiesProvider/AiTaskSelectorPropertiesProvider";
import aiTaskSelectorRendererModule from "@/bpmn/aiTaskSelectorRenderer";
import scriptTaskPropertiesProviderModule from "@/bpmn/scriptTaskPropertiesProvider/ScriptTaskPropertiesProvider";
import businessRuleTaskPropertiesProviderModule from "@/bpmn/businessRuleTaskPropertiesProvider/BusinessRuleTaskPropertiesProvider";
import timerPropertiesProviderModule from "@/bpmn/timerPropertiesProvider";
import startEventPropertiesProviderModule from "@/bpmn/startEventPropertiesProvider/StartEventPropertiesProvider";
import conditionalStartEventPropertiesProviderModule from "@/bpmn/conditionalStartEventPropertiesProvider/ConditionalStartEventPropertiesProvider";
import lanePropertiesProviderModule from "@/bpmn/lanePropertiesProvider/LanePropertiesProvider";
import signalPropertiesProviderModule from "@/bpmn/signalPropertiesProvider/SignalPropertiesProvider";
import propertiesPanelFilterModule from "@/bpmn/propertiesPanelFilter";
import commentContextPadModule from "@/bpmn/commentContextPad";
import { registerSpiffExtensions } from "@/utils/editorModdleExtensions";
import { clipboardModule, nativeCopyPasteModule } from "./useEditorCopyPaste";
import { lintModule, bpmnlintConfig } from "./useEditorLint";
// Touch gestures for the editor and the instance viewer: tap, drag a shape, pan, pinch, double-tap.
import touchInteractionModule from "bpmn-js-touch-interaction";
import "bpmn-js/dist/assets/diagram-js.css";
import "bpmn-js/dist/assets/bpmn-js.css";
import "bpmn-js/dist/assets/bpmn-font/css/bpmn.css";
import "@bpmn-io/properties-panel/dist/assets/properties-panel.css";

export function useEditorModeler(ed) {
	const { props, emit, isMounted, modelerInstance, container, propertiesContainer, toolbarEl } =
		ed;

	onMounted(async () => {
		isMounted.value = true;
		try {
			registerSpiffExtensions();

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
						serviceTaskPropertiesProviderModule,
						aiAgentPropertiesProviderModule,
						aiAgentReplaceMenuProviderModule,
						aiAgentRendererModule,
						adhocSubprocessPropertiesProviderModule,
						aiTaskSelectorMenuProviderModule,
						aiTaskSelectorPropertiesProviderModule,
						aiTaskSelectorRendererModule,

						scriptTaskPropertiesProviderModule,
						businessRuleTaskPropertiesProviderModule,
						timerPropertiesProviderModule,
						startEventPropertiesProviderModule,
						conditionalStartEventPropertiesProviderModule,
						lanePropertiesProviderModule,
						signalPropertiesProviderModule,
						translateModule,
						customTextStyleModule,
						resizeModule,
						stickyNoteModule,
						serviceTaskIconModule,
						clipboardModule,
						lintModule,
						nativeCopyPasteModule,
						touchInteractionModule,
						propertiesPanelFilterModule,
						commentContextPadModule,
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
					// In bpmn-js v18+, keyboard binds to the canvas automatically.
					// Disable keyboard entirely in readonly mode.
					keyboard: props.readonly ? false : {},
				},
				onReady: async (initializedModeler) => {
					ed.modeler = initializedModeler;
					modelerInstance.value = initializedModeler;
					ed.commandStack = initializedModeler.get("commandStack");
					for (const step of ed.readySteps) await step();
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
		// Cancel any pending process-name injection to prevent memory-leaks
		// and stale DOM updates after the component is torn down.
		cancelPendingInjection();
		if (ed.modeler) {
			ed.modeler.destroy();
		}
	});
}
