/**
 * Service Task Icon Renderer Module
 *
 * Replaces the generic gear marker on a bpmn:ServiceTask with a
 * service-specific Material Design icon, based on the
 * spiffworkflow:serviceType attribute.
 *
 * Implemented as a custom diagram-js renderer (same pattern as
 * StickyNoteRenderer): when a service type is set we draw the plain
 * task box via the built-in "bpmn:Task" handler (which omits the gear)
 * and paint our own icon in the gear's spot. When no service type is
 * set, canRender() returns false and the default bpmn-js renderer draws
 * the standard gear marker as before.
 */

import BaseRenderer from "diagram-js/lib/draw/BaseRenderer";

// Must beat the default BpmnRenderer (priority 1000)
const HIGH_PRIORITY = 1500;

const SVG_NS = "http://www.w3.org/2000/svg";

// Rounded-corner radius used by the default bpmn-js task shape
const TASK_BORDER_RADIUS = 10;

// Rendered icon size (px) and its top-left offset inside the task box —
// chosen to sit where the default gear marker would be.
const ICON_SIZE = 20;
const ICON_OFFSET = 5;

// ---------------------------------------------------------------------------
// Icon definitions — inline SVG paths extracted from @iconify-json/mdi.
// All MDI icons use a 24×24 viewBox.
// ---------------------------------------------------------------------------
const SERVICE_ICONS = {
	apply_workflow: {
		label: "Apply Workflow",
		color: "#6366f1", // indigo-500
		// mdi:state-machine
		path: "M6.27 17.05A2.991 2.991 0 0 1 4 22c-1.66 0-3-1.34-3-3s1.34-3 3-3c.18 0 .36 0 .53.05l3.07-5.36-1.74-.99 4.09-1.12 1.12 4.09-1.74-.99zM20 16c-1.3 0-2.4.84-2.82 2H11v-2l-3 3 3 3v-2h6.18c.42 1.16 1.52 2 2.82 2 1.66 0 3-1.34 3-3s-1.34-3-3-3m-8-8c.18 0 .36 0 .53-.05l3.07 5.36-1.74.99 4.09 1.12 1.12-4.09-1.74.99-3.06-5.37A2.991 2.991 0 0 0 12 2c-1.66 0-3 1.34-3 3s1.34 3 3 3",
	},
	send_email: {
		label: "Email Notification",
		color: "#0ea5e9", // sky-500
		// mdi:email-outline
		path: "M22 6c0-1.1-.9-2-2-2H4c-1.1 0-2 .9-2 2v12c0 1.1.9 2 2 2h16c1.1 0 2-.9 2-2zm-2 0-8 5-8-5zm0 12H4V8l8 5 8-5z",
	},
	update_field: {
		label: "Update Field",
		color: "#f59e0b", // amber-500
		// mdi:form-textbox
		path: "M17 7h5v10h-5v2a1 1 0 0 0 1 1h2v2h-2.5c-.55 0-1.5-.45-1.5-1 0 .55-.95 1-1.5 1H12v-2h2a1 1 0 0 0 1-1V5a1 1 0 0 0-1-1h-2V2h2.5c.55 0 1.5.45 1.5 1 0-.55.95-1 1.5-1H20v2h-2a1 1 0 0 0-1 1zM2 7h11v2H4v6h9v2H2zm18 8V9h-3v6z",
	},
	google_chat: {
		label: "Google Chat",
		color: "#22c55e", // green-500
		// mdi:chat-outline
		path: "M12 3C6.5 3 2 6.58 2 11a7.22 7.22 0 0 0 2.75 5.5c0 .6-.42 2.17-2.75 4.5 2.37-.11 4.64-1 6.47-2.5 1.14.33 2.34.5 3.53.5 5.5 0 10-3.58 10-8s-4.5-8-10-8m0 14c-4.42 0-8-2.69-8-6s3.58-6 8-6 8 2.69 8 6-3.58 6-8 6",
	},
	push_notification: {
		label: "Push Notification",
		color: "#ef4444", // red-500
		// mdi:bell-ring-outline
		path: "M10 21h4a2 2 0 0 1-2 2 2 2 0 0 1-2-2m11-2v1H3v-1l2-2v-6c0-3.1 2.03-5.83 5-6.71V4a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.29c2.97.88 5 3.61 5 6.71v6zm-4-8a5 5 0 0 0-5-5 5 5 0 0 0-5 5v7h10zm2.75-7.81-1.42 1.42A8.98 8.98 0 0 1 21 11h2c0-2.93-1.16-5.75-3.25-7.81M1 11h2c0-2.4.96-4.7 2.67-6.39L4.25 3.19A10.96 10.96 0 0 0 1 11",
	},
};

function getServiceIcon(element) {
	const bo = element.businessObject;
	if (!bo) return null;
	const serviceType = bo.get("spiffworkflow:serviceType") || "";
	return SERVICE_ICONS[serviceType] || null;
}

function roundRectPath(x, y, width, height, r) {
	return [
		"M", x + r, y,
		"l", width - r * 2, 0,
		"a", r, r, 0, 0, 1, r, r,
		"l", 0, height - r * 2,
		"a", r, r, 0, 0, 1, -r, r,
		"l", -(width - r * 2), 0,
		"a", r, r, 0, 0, 1, -r, -r,
		"l", 0, -(height - r * 2),
		"a", r, r, 0, 0, 1, r, -r,
		"z",
	].join(" ");
}

// ---------------------------------------------------------------------------
// Renderer
// ---------------------------------------------------------------------------
export default class ServiceTaskIconRenderer extends BaseRenderer {
	constructor(eventBus, bpmnRenderer) {
		super(eventBus, HIGH_PRIORITY);
		this.bpmnRenderer = bpmnRenderer;
	}

	canRender(element) {
		// Only take over ServiceTask shapes that have a known service type;
		// everything else falls through to the default renderer (gear marker).
		return (
			element.type === "bpmn:ServiceTask" &&
			!element.labelTarget &&
			!!getServiceIcon(element)
		);
	}

	drawShape(parentGfx, element) {
		// Draw the plain task box (rounded rect + loop/multi-instance markers)
		// using the built-in handler. This deliberately skips the service gear.
		const task = this.bpmnRenderer._renderer("bpmn:Task")(parentGfx, element);

		// Paint the service-specific icon where the gear would have been.
		const iconDef = getServiceIcon(element);
		if (iconDef) {
			const scale = ICON_SIZE / 24;
			const group = document.createElementNS(SVG_NS, "g");
			group.setAttribute(
				"transform",
				`translate(${ICON_OFFSET}, ${ICON_OFFSET}) scale(${scale})`,
			);

			const path = document.createElementNS(SVG_NS, "path");
			path.setAttribute("d", iconDef.path);
			path.setAttribute("fill", iconDef.color);
			group.appendChild(path);

			const title = document.createElementNS(SVG_NS, "title");
			title.textContent = iconDef.label;
			group.appendChild(title);

			parentGfx.appendChild(group);
		}

		return task;
	}

	getShapePath(shape) {
		const { x, y, width, height } = shape;
		// Mirror the default task outline so connection cropping is unchanged.
		return roundRectPath(x, y, width, height, TASK_BORDER_RADIUS);
	}
}

ServiceTaskIconRenderer.$inject = ["eventBus", "bpmnRenderer"];

// Module definition for bpmn-js
export const serviceTaskIconModule = {
	__init__: ["serviceTaskIconRenderer"],
	serviceTaskIconRenderer: ["type", ServiceTaskIconRenderer],
};
