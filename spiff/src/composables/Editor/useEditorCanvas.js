import { onUnmounted } from "vue";
import { reinjectIfCalledElementChanged } from "@/composables/useCallActivityName";

export function useEditorCanvas(ed) {
	const { props, emit, propertiesContainer, canUndo, canRedo, zoomLevel, isImporting } = ed;

	function updateUndoRedoState() {
		if (ed.commandStack) {
			canUndo.value = ed.commandStack.canUndo();
			canRedo.value = ed.commandStack.canRedo();
		}
		// Suppress change events in readonly mode so auto-save doesn't fire
		if (!isImporting.value && !props.readonly) {
			emit("changed");
		}
	}

	function undo() {
		if (ed.commandStack && ed.commandStack.canUndo()) {
			ed.commandStack.undo();
		}
	}

	function redo() {
		if (ed.commandStack && ed.commandStack.canRedo()) {
			ed.commandStack.redo();
		}
	}

	function deleteSelected() {
		if (!ed.modeler) return;
		const selection = ed.modeler.get("selection");
		const modeling = ed.modeler.get("modeling");
		const selected = selection.get();
		if (selected && selected.length > 0) {
			modeling.removeElements(selected); // goes through the intercept in onReady
		}
	}

	function addStickyNote() {
		if (!ed.modeler) return;

		const modeling = ed.modeler.get("modeling");
		const canvas = ed.modeler.get("canvas");
		const bpmnFactory = ed.modeler.get("bpmnFactory");
		const elementFactory = ed.modeler.get("elementFactory");

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
		const selection = ed.modeler.get("selection");
		selection.select(shape);

		const directEditing = ed.modeler.get("directEditing");
		// Small delay to ensure the SVG is rendered before activating editor
		setTimeout(() => {
			if (directEditing.canActivate(shape)) {
				directEditing.activate(shape);
			}
		}, 100);
	}

	function zoomIn() {
		if (!ed.modeler) return;
		const canvas = ed.modeler.get("canvas");
		const currentZoom = canvas.zoom();
		const newZoom = Math.min(currentZoom * 1.1, 4); // Max 400%
		canvas.zoom(newZoom);
		zoomLevel.value = Math.round(newZoom * 100);
	}

	function zoomOut() {
		if (!ed.modeler) return;
		const canvas = ed.modeler.get("canvas");
		const currentZoom = canvas.zoom();
		const newZoom = Math.max(currentZoom / 1.1, 0.1); // Min 10%
		canvas.zoom(newZoom);
		zoomLevel.value = Math.round(newZoom * 100);
	}

	function resetZoom() {
		if (!ed.modeler) return;
		const canvas = ed.modeler.get("canvas");
		canvas.zoom(1);
		zoomLevel.value = 100;
	}

	function fitToScreen() {
		if (!ed.modeler) return;
		const canvas = ed.modeler.get("canvas");
		canvas.zoom("fit-viewport");
		zoomLevel.value = Math.round(canvas.zoom() * 100);
	}

	function getZoomLevel() {
		return zoomLevel.value;
	}

	// Overlay API functions
	function getOverlays() {
		if (!ed.modeler) return null;
		return ed.modeler.get("overlays");
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
		if (!ed.modeler) return;
		const modeling = ed.modeler.get("modeling");
		const elementRegistry = ed.modeler.get("elementRegistry");

		const ids = Array.isArray(elementIds) ? elementIds : [elementIds];
		const elements = ids.map((id) => elementRegistry.get(id)).filter(Boolean);

		if (elements.length > 0) {
			modeling.setColor(elements, { stroke, fill });
		}
	}

	function clearElementColor(elementIds) {
		if (!ed.modeler) return;
		const modeling = ed.modeler.get("modeling");
		const elementRegistry = ed.modeler.get("elementRegistry");

		const ids = Array.isArray(elementIds) ? elementIds : [elementIds];
		const elements = ids.map((id) => elementRegistry.get(id)).filter(Boolean);

		if (elements.length > 0) {
			modeling.setColor(elements, null);
		}
	}

	function getSelectedElements() {
		if (!ed.modeler) return [];
		const selection = ed.modeler.get("selection");
		return selection.get();
	}

	// Directly update a Call Activity's Process and its active map's id via the command stack.
	// This is the reliable way to update the property regardless of SpiffWorkflow's
	// async once-listener state.
	function updateCalledElement(element, processId, process) {
		if (!ed.modeler || !element) return;
		const cmdStack = ed.modeler.get("commandStack");
		cmdStack.execute("element.updateProperties", {
			element,
			moddleElement: element.businessObject,
			properties: { calledElement: processId, "spiffworkflow:calledProcess": process },
		});
		// Force the properties panel to re-initialize (and re-read getValue)
		// by cycling the selection. Without this the Preact TextFieldEntry
		// shows stale data until the page is refreshed.
		const selection = ed.modeler.get("selection");
		selection.select(null);
		setTimeout(() => {
			selection.select(element);
		}, 30);
	}

	ed.onReady(() => {
		const eventBus = ed.modeler.get("eventBus");
		// The drilldown arrow alerts when calledElement is empty; route a Process-name link instead
		const canvasContainer = ed.modeler.get("canvas").getContainer();
		const launchProcessNameLink = (event) => {
			if (!event.target.closest(".bjs-drilldown")) return;
			const [element] = ed.modeler.get("selection").get();
			const businessObject = element?.businessObject;
			if (
				businessObject?.calledElement ||
				!businessObject?.get("spiffworkflow:calledProcess")
			)
				return;
			event.stopPropagation();
			emit("launch-callactivity-editor", { processId: "", element });
		};
		canvasContainer.addEventListener("click", launchProcessNameLink, true);
		onUnmounted(() => {
			canvasContainer.removeEventListener("click", launchProcessNameLink, true);
		});

		// Re-inject only when calledElement actually changed
		// churn and repeated network requests on every command stack event.
		eventBus.on("commandStack.changed", () => {
			updateUndoRedoState();
			const selection = ed.modeler.get("selection");
			const selected = selection.get();
			if (selected?.length === 1 && selected[0]?.type === "bpmn:CallActivity") {
				reinjectIfCalledElementChanged(selected[0], propertiesContainer);
			}
			// Force properties panel to refresh and update dynamic properties (like Service Task fields)
			try {
				eventBus.fire("propertiesPanel.providersChanged");
			} catch (e) {
				console.warn("Failed to fire propertiesPanel.providersChanged:", e);
			}
		});

		// Listen for zoom changes (Ctrl+scroll, programmatic zoom, etc.)
		eventBus.on("canvas.viewbox.changed", () => {
			const canvas = ed.modeler.get("canvas");
			const newZoom = Math.round(canvas.zoom() * 100);
			zoomLevel.value = newZoom;
			emit("zoom-changed", newZoom);
		});

		// Ensure comments are rendered after any diagram import finishes
		eventBus.on("import.done", () => {
			ed.renderComments();
		});
	});

	Object.assign(ed, {
		updateUndoRedoState,
		undo,
		redo,
		deleteSelected,
		addStickyNote,
		zoomIn,
		zoomOut,
		resetZoom,
		fitToScreen,
		getZoomLevel,
		getOverlays,
		addOverlay,
		removeOverlay,
		removeOverlaysByElement,
		clearAllOverlays,
		setElementColor,
		clearElementColor,
		getSelectedElements,
		updateCalledElement,
	});
}
