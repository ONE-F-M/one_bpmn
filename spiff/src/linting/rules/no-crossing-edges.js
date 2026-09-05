/**
 * Custom bpmnlint rule: no-crossing-edges
 *
 * Reports sequence flows whose lines cross another flow, and lines that pass
 * through a shape they do not connect. Runs once, on bpmn:Definitions, over the
 * diagram's DI; the geometry is shared with the compiler (spiff/pipeline.mjs)
 * so the modeler and the pipeline agree on what a crossing is.
 *
 * A non-planar process cannot be drawn with zero crossings, which is why this
 * is a warning: the reader should know a line crosses, not be told it is wrong.
 */

import { is } from "bpmnlint-utils";
import { auditGeometry } from "../geometry.js";

function box(b) {
	return b ? { x: b.x, y: b.y, w: b.width, h: b.height } : null;
}

export default function () {
	function check(node, reporter) {
		if (!is(node, "bpmn:Definitions")) return;
		const plane = ((node.diagrams || [])[0] || {}).plane;
		if (!plane) return;

		const shapes = [], edges = [];
		for (const el of plane.planeElement || []) {
			const be = el.bpmnElement;
			if (is(el, "bpmndi:BPMNShape") && el.bounds) {
				shapes.push({
					id: be && be.id, name: be && be.name,
					...box(el.bounds),
					container: !!(be && (is(be, "bpmn:Participant") || is(be, "bpmn:Lane"))),
					label: el.label ? box(el.label.bounds) : null,
				});
			} else if (is(el, "bpmndi:BPMNEdge") && el.waypoint && el.waypoint.length > 1) {
				edges.push({
					id: be && be.id, name: be && be.name,
					pts: el.waypoint.map((w) => [w.x, w.y]),
					src: be && be.sourceRef && be.sourceRef.id,
					tgt: be && be.targetRef && be.targetRef.id,
					label: el.label ? box(el.label.bounds) : null,
				});
			}
		}
		if (!edges.length) return;

		const result = auditGeometry({ shapes, edges });
		const label = (id) => {
			const s = shapes.find((x) => x.id === id) || edges.find((x) => x.id === id);
			return s && s.name ? `"${s.name}"` : id;
		};
		for (const p of result.crossingPairs) {
			reporter.report(p.a, `Line crosses ${label(p.b)}.`);
		}
		for (const p of result.throughPairs) {
			reporter.report(p.edge, `Line passes through ${label(p.shape)}, which it does not connect.`);
		}
	}

	return { check };
}
