// Needed for gestures canvasTouchHandler lacks: dragging a shape (the handler pans instead), double-tap, palette and tool gestures.
import touchInteractionModule from "bpmn-js-touch-interaction";

export { touchInteractionModule };

import { setupCanvasTouchHandler } from "@/utils/canvasTouchHandler";

export function useEditorTouch(ed) {
	const { container } = ed;

	ed.onReady(() => {
		// Direct touch handler fallback: only activate when the device has
		// touch capability but the bpmn-js-touch-interaction module didn't
		// initialize (it gates on `(pointer: coarse)` which returns false
		// on some mobile browsers). This avoids duplicate gesture handlers.
		const isTouchDevice = "ontouchstart" in window || navigator.maxTouchPoints > 0;
		const moduleActivated = window.matchMedia("(pointer: coarse)").matches;
		if (!ed.editorTouchCleanup && container.value && isTouchDevice && !moduleActivated) {
			ed.editorTouchCleanup = setupCanvasTouchHandler(ed.modeler, container.value);
		}
	});
}
