import BaseRenderer from "diagram-js/lib/draw/BaseRenderer";
import { is, getBusinessObject } from "bpmn-js/lib/util/ModelUtil";
import { append as svgAppend, create as svgCreate } from "tiny-svg";
import { AI_SPARKLE_DATA_URI } from "../shared/aiSparkleIcon";

const HIGH_PRIORITY = 1500;

/**
 * Badge renderer for Ad-hoc Subprocesses tagged with an AI Task Selector
 * (WI-001360). Draws the shared AI sparkle in the top-left of the
 * subprocess shape — the plain ad-hoc tilde marker is kept (stock
 * rendering), the sparkle signals "an LLM decides what runs next here"
 * and matches the AI Agent Task icon.
 */
export default class AiTaskSelectorRenderer extends BaseRenderer {
	constructor(eventBus, bpmnRenderer) {
		super(eventBus, HIGH_PRIORITY);
		this.bpmnRenderer = bpmnRenderer;
	}

	canRender(element) {
		const bo = getBusinessObject(element);
		if (!bo || !is(element, "bpmn:AdHocSubProcess")) {
			return false;
		}
		// $attrs fallback: hosts whose moddle doesn't declare the extension
		// still keep unknown namespaced attributes there.
		const serviceType =
			bo.get("spiffworkflow:serviceType") ??
			(bo.$attrs && bo.$attrs["spiffworkflow:serviceType"]);
		return serviceType === "ai_task_selector";
	}

	drawShape(parentNode, element) {
		const shape = this.bpmnRenderer.drawShape(parentNode, element);

		const icon = svgCreate("image", {
			x: 5,
			y: 5,
			width: 18,
			height: 18,
			href: AI_SPARKLE_DATA_URI,
		});
		svgAppend(parentNode, icon);

		return shape;
	}

	getShapePath(shape) {
		return this.bpmnRenderer.getShapePath(shape);
	}
}

AiTaskSelectorRenderer.$inject = ["eventBus", "bpmnRenderer"];
