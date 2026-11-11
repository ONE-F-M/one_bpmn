import {
	PROPERTY_COMMANDS,
	conditionalDefinition,
	isConditionUpdate,
	isEditableProperty as isPanelEditableProperty,
	isLockedElement as isPanelLockedElement,
} from "@/bpmn/shared/releasedPanel";

export function useEditorReadonly(ed) {
	const { props, emit } = ed;

	ed.onReady(() => {
		// In readonly mode, disable all modeler-level editing interactions
		// so users cannot move, delete, or modify elements locally.
		if (props.readonly) {
			// Intercept commandStack to prevent any model mutations
			const originalExecute = ed.commandStack.execute.bind(ed.commandStack);

			// "Release Property Panel" mode: while readonly, the properties
			// panel may edit flow objects - but only what a step DOES, never
			// what the map IS. The carve-outs live in
			// @/bpmn/shared/releasedPanel and mirror
			// one_bpmn/api/property_panel.py, which enforces them again on
			// save; that module's header explains each one.
			const isPropertyCommand = (command, context) => {
				if (!props.reassignMode) return false;
				if (!PROPERTY_COMMANDS.includes(command)) return false;
				const bo = context?.element?.businessObject;
				if (isPanelLockedElement(bo)) return false;
				// A flow's condition arrives as a moddle update on the
				// expression element itself, carrying no properties.
				if (isConditionUpdate(bo, context.moddleElement)) return true;
				// Any other moddle update on a nested element (an extension
				// element, a timer definition) is not saved by the endpoint.
				if (
					command === "element.updateModdleProperties" &&
					context.moddleElement !== bo &&
					context.moddleElement !== conditionalDefinition(bo)
				) {
					return false;
				}
				const keys = Object.keys(context.properties || {});
				return keys.length > 0 && keys.every(isPanelEditableProperty);
			};

			ed.commandStack.execute = (command, context) => {
				// Allow canvas operations (zoom, scroll) but block element mutations
				const allowedCommands = ["canvas.updateRootElement"];
				if (allowedCommands.includes(command)) {
					return originalExecute(command, context);
				}
				if (isPropertyCommand(command, context)) {
					const result = originalExecute(command, context);
					const bo = context.element.businessObject;
					// Send back exactly the keys this command touched, so a
					// property the panel did not change is never rewritten.
					const properties = {};
					if (isConditionUpdate(bo, context.moddleElement)) {
						properties.conditionExpression = context.moddleElement.body || "";
					}
					const target = context.moddleElement || bo;
					Object.keys(context.properties || {}).forEach((key) => {
						properties[String(key).split(":").pop()] = target.get(key) || "";
					});
					emit("reassign-changed", { taskId: bo.id, assignment: properties });
					return result;
				}
				// Silently ignore all other commands
				return;
			};

			// Disable direct editing (double-click labels)
			try {
				const directEditing = ed.modeler.get("directEditing");
				if (directEditing) {
					directEditing.cancel();
					directEditing.activate = () => false;
				}
			} catch {
				/* module may not exist */
			}

			// Disable dragging
			try {
				const dragging = ed.modeler.get("dragging");
				if (dragging) {
					dragging.init = () => {};
				}
			} catch {
				/* module may not exist */
			}
		}
	});
}
