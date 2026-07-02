import BaseRenderer from "diagram-js/lib/draw/BaseRenderer";
import { is, getBusinessObject } from "bpmn-js/lib/util/ModelUtil";
import { append as svgAppend, create as svgCreate } from "tiny-svg";

const HIGH_PRIORITY = 1500;

// Wrench/tool glyph — deliberately DISTINCT from the AI Agent Task sparkle
// (WI-001360 Scenario 3) so the two AI element kinds are visually
// distinguishable on the diagram.
const WRENCH_DATA_URI =
	"data:image/svg+xml;utf8," +
	encodeURIComponent(
		'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" ' +
			'stroke="#6b46c1" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">' +
			'<path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z"/>' +
			"</svg>"
	);

/**
 * Badge renderer for Ad-hoc Subprocesses tagged with an AI Task Selector
 * (WI-001360). Draws a wrench marker in the top-left of the subprocess
 * shape — the plain ad-hoc tilde marker is kept (stock rendering), the
 * wrench signals "an LLM decides what runs next here".
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
			href: WRENCH_DATA_URI,
		});
		svgAppend(parentNode, icon);

		return shape;
	}

	getShapePath(shape) {
		return this.bpmnRenderer.getShapePath(shape);
	}
}

AiTaskSelectorRenderer.$inject = ["eventBus", "bpmnRenderer"];
