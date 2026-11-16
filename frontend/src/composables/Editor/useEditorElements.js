import { frappeRequest } from "frappe-ui";
import {
	cancelPendingInjection,
	injectProcessNameField,
	removeProcessNameField,
} from "@/composables/useCallActivityName";

export function useEditorElements(ed) {
	const {
		props,
		emit,
		timelineFilterMode,
		propertiesContainer,
		showPropertiesPanel,
		propertiesCollapsed,
		selectedElements,
	} = ed;

	function getLinkedScriptNames(elements) {
		const names = new Set();
		for (const el of elements) {
			const bo = el.businessObject;
			if (!bo) continue;
			// bpmn:ScriptTask stores the server script name in `script` field
			if (bo.$type === "bpmn:ScriptTask" && bo.script && bo.script.trim()) {
				names.add(bo.script.trim());
			}
			// Pre/PostScript stored in extensionElements
			const exts = bo.extensionElements?.get("values") || [];
			for (const ext of exts) {
				const tag = ext.$type || "";
				if (
					(tag === "spiffworkflow:PreScript" || tag === "spiffworkflow:PostScript") &&
					ext.value?.trim()
				) {
					names.add(ext.value.trim());
				}
			}
		}
		return [...names];
	}

	function countScriptUsageAcrossCanvas(scriptNames) {
		if (!ed.modeler || !scriptNames.length) return {};
		const registry = ed.modeler.get("elementRegistry");
		const counts = Object.fromEntries(scriptNames.map((n) => [n, 0]));
		registry.forEach((el) => {
			const bo = el.businessObject;
			if (!bo) return;
			if (bo.$type === "bpmn:ScriptTask" && bo.script?.trim()) {
				if (counts[bo.script.trim()] !== undefined) counts[bo.script.trim()]++;
			}
			const exts = bo.extensionElements?.get("values") || [];
			for (const ext of exts) {
				const tag = ext.$type || "";
				if (
					(tag === "spiffworkflow:PreScript" || tag === "spiffworkflow:PostScript") &&
					ext.value?.trim()
				) {
					if (counts[ext.value.trim()] !== undefined) counts[ext.value.trim()]++;
				}
			}
		});
		return counts;
	}

	ed.onReady(() => {
		const eventBus = ed.modeler.get("eventBus");
		// Intercept modeling.removeElements so ALL deletion paths trigger the
		// script-delete confirmation (context pad, keyboard, toolbar).
		if (!props.readonly) {
			const modeling = ed.modeler.get("modeling");
			const origRemoveElements = modeling.removeElements.bind(modeling);
			modeling.removeElements = function (elements) {
				if (!Array.isArray(elements) || elements.length === 0) {
					return origRemoveElements(elements);
				}
				const scriptNames = getLinkedScriptNames(elements);
				if (scriptNames.length > 0) {
					const usageMap = countScriptUsageAcrossCanvas(scriptNames);
					emit("confirm-script-delete", {
						elements,
						scriptNames,
						usageMap,
						doDelete: origRemoveElements,
					});
					return;
				}
				return origRemoveElements(elements);
			};
		}

		// Clear custom trigger attributes if a StartEvent is converted into something else
		// (e.g. Timer Start Event) so they don't persist in the XML.
		// Use modeling.updateModdleProperties so the operation is tracked by the command
		// stack and is properly undoable/redoable.
		eventBus.on("commandStack.shape.replace.postExecute", (e) => {
			const newShape = e.context.newShape;
			const bo = newShape && newShape.businessObject;
			if (!bo) return;

			const modeling = ed.modeler.get("modeling");
			const triggerAttrs = [
				"triggerDoctype",
				"triggerType",
				"triggerWorkflow",
				"triggerWorkflowState",
			];
			const clearProps = {};
			triggerAttrs.forEach((attr) => {
				clearProps[`spiffworkflow:${attr}`] = undefined;
			});

			if (bo.$type === "bpmn:StartEvent") {
				const eventDefs = bo.get("eventDefinitions") || [];
				const isPlainStartEvent = eventDefs.length === 0;
				const hasConditionalDef = eventDefs.some(
					(d) => d.$type === "bpmn:ConditionalEventDefinition",
				);

				// Clear trigger attrs from the StartEvent BO if it has event definitions
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
						const oldCondDef = oldDefs.find(
							(d) => d.$type === "bpmn:ConditionalEventDefinition",
						);
						if (oldCondDef) {
							modeling.updateModdleProperties(newShape, oldCondDef, clearProps);
						}
					}
				}
			} else {
				// Not a StartEvent at all - clear any lingering trigger attrs
				modeling.updateModdleProperties(newShape, bo, clearProps);
			}
		});

		// Cleanup comments and ToDos when an element is deleted
		eventBus.on("commandStack.elements.delete.postExecute", (e) => {
			const elements = e.context.elements || [];
			elements.forEach((element) => {
				if (element.id && props.modelName) {
					frappeRequest({
						url: "/api/method/processa.api.canvas_comments.delete_canvas_element_assets",
						params: {
							model_name: props.modelName,
							element_id: element.id,
						},
					}).then(() => {
						// Refresh comments to reflect deletion
						ed.fetchComments();
					});
				}
			});
		});

		// Listen for selection changes for formatting toolbar
		eventBus.on("selection.changed", (e) => {
			selectedElements.value = e.newSelection || [];
			emit("selection-changed", selectedElements.value.map((el) => el.id));

			// Auto-open the properties panel when an element is selected
			if (e.newSelection?.length > 0) {
				showPropertiesPanel.value = true;
				timelineFilterMode.value = "element";
				if (!ed.isMobile.value) {
					propertiesCollapsed.value = false;
				}
			}

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
	});

	Object.assign(ed, { getLinkedScriptNames, countScriptUsageAcrossCanvas });
}
