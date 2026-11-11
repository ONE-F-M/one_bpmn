import BaseRenderer from "diagram-js/lib/draw/BaseRenderer";
import { is, getBusinessObject } from "bpmn-js/lib/util/ModelUtil";
import { append as svgAppend, create as svgCreate } from "tiny-svg";
import { AI_SPARKLE_DATA_URI } from "../shared/aiSparkleIcon";

// Render above the default BpmnRenderer (priority 1000) so this takes over for
// AI Agent Tasks.
const HIGH_PRIORITY = 1500;

/**
 * Custom renderer that gives AI Agent Tasks (ServiceTasks tagged
 * spiffworkflow:serviceType="ai_agent") a sparkle icon on the canvas instead
 * of the default Service Task gear.
 */
export default class AiAgentRenderer extends BaseRenderer {
	constructor(eventBus, bpmnRenderer) {
		super(eventBus, HIGH_PRIORITY);
		this.bpmnRenderer = bpmnRenderer;
	}

	canRender(element) {
		const bo = getBusinessObject(element);
		return (
			is(element, "bpmn:ServiceTask") &&
			bo &&
			bo.get("spiffworkflow:serviceType") === "ai_agent"
		);
	}

	drawShape(parentNode, element) {
		// Draw the standard task shape (rounded rectangle + label) first.
		const shape = this.bpmnRenderer.drawShape(parentNode, element);

		// Cover the default Service Task gear (top-left) and draw the sparkle.
		const cover = svgCreate("rect", {
			x: 3,
			y: 3,
			width: 24,
			height: 24,
			fill: "#ffffff",
		});
		svgAppend(parentNode, cover);

		const icon = svgCreate("image", {
			x: 4,
			y: 4,
			width: 22,
			height: 22,
			href: AI_SPARKLE_DATA_URI,
		});
		svgAppend(parentNode, icon);

		return shape;
	}

	getShapePath(shape) {
		return this.bpmnRenderer.getShapePath(shape);
	}
}

AiAgentRenderer.$inject = ["eventBus", "bpmnRenderer"];
