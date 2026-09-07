/**
 * Diagram geometry shared by the compiler (pipeline.mjs) and the modeler lint
 * rule (no-crossing-edges). Pure functions over plain numbers, no DOM, no moddle.
 *
 * Shapes:  { id, name?, x, y, w, h, container, label?: {x,y,w,h} }
 * Edges:   { id, name?, pts: [[x,y], ...], src, tgt, label?: {x,y,w,h} }
 */

const EPS = 1e-6;

function orient(a, b, c) {
	const v = (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0]);
	return Math.abs(v) < EPS ? 0 : v > 0 ? 1 : -1;
}

function samePoint(p, q) {
	return Math.abs(p[0] - q[0]) < EPS && Math.abs(p[1] - q[1]) < EPS;
}

/** Two segments form an X. Touching at an endpoint is not a crossing. */
export function properCross(s1, s2) {
	const [p1, p2] = s1, [p3, p4] = s2;
	if (samePoint(p1, p3) || samePoint(p1, p4) || samePoint(p2, p3) || samePoint(p2, p4)) return false;
	const o1 = orient(p1, p2, p3), o2 = orient(p1, p2, p4);
	const o3 = orient(p3, p4, p1), o4 = orient(p3, p4, p2);
	return o1 !== o2 && o3 !== o4 && o1 !== 0 && o2 !== 0 && o3 !== 0 && o4 !== 0;
}

/** Two axis-aligned segments lie on one line and share a stretch of it. */
export function collinearOverlap(s1, s2) {
	const [p1, p2] = s1, [p3, p4] = s2;
	for (const i of [0, 1]) {
		const j = 1 - i;
		const fixed = Math.abs(p1[i] - p2[i]) < EPS && Math.abs(p3[i] - p4[i]) < EPS && Math.abs(p1[i] - p3[i]) < EPS;
		if (!fixed) continue;
		const lo = Math.max(Math.min(p1[j], p2[j]), Math.min(p3[j], p4[j]));
		const hi = Math.min(Math.max(p1[j], p2[j]), Math.max(p3[j], p4[j]));
		return hi - lo > EPS;
	}
	return false;
}

/** An axis-aligned segment passes through the interior of a box. */
export function segHitsBox(seg, box) {
	const [[ax, ay], [bx, by]] = seg;
	const x0 = box.x, y0 = box.y, x1 = box.x + box.w, y1 = box.y + box.h;
	if (Math.abs(ax - bx) < EPS) {
		if (!(x0 < ax && ax < x1)) return false;
		return !(Math.max(ay, by) <= y0 || Math.min(ay, by) >= y1);
	}
	if (Math.abs(ay - by) < EPS) {
		if (!(y0 < ay && ay < y1)) return false;
		return !(Math.max(ax, bx) <= x0 || Math.min(ax, bx) >= x1);
	}
	return false;
}

export function boxesHit(a, b) {
	return a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h;
}

function segments(pts) {
	const out = [];
	for (let i = 1; i < pts.length; i++) out.push([pts[i - 1], pts[i]]);
	return out;
}

/**
 * Count crossings, collinear overlaps, edges through shapes, and label
 * collisions. Edges that share a node may touch at that node without penalty.
 */
export function auditGeometry({ shapes, edges }) {
	const crossingPairs = [], overlapPairs = [], throughPairs = [], labelPairs = [];
	const segsOf = edges.map(e => segments(e.pts || []));
	const nodes = shapes.filter(s => !s.container);

	for (let i = 0; i < edges.length; i++) {
		for (let j = i + 1; j < edges.length; j++) {
			const a = edges[i], b = edges[j];
			const shared = a.src && b.src && (a.src === b.src || a.src === b.tgt || a.tgt === b.src || a.tgt === b.tgt);
			let crossed = false, overlapped = false;
			for (const s1 of segsOf[i]) {
				for (const s2 of segsOf[j]) {
					if (properCross(s1, s2)) {
						// A shared node's stub may fan out from one point; anything else is a real X.
						if (shared && (samePoint(s1[0], s2[0]) || samePoint(s1[0], s2[1]) || samePoint(s1[1], s2[0]) || samePoint(s1[1], s2[1]))) continue;
						crossed = true;
					} else if (collinearOverlap(s1, s2)) {
						overlapped = true;
					}
				}
			}
			if (crossed) crossingPairs.push({ a: a.id, b: b.id });
			if (overlapped) overlapPairs.push({ a: a.id, b: b.id });
		}
	}

	for (let i = 0; i < edges.length; i++) {
		const e = edges[i];
		for (const shape of nodes) {
			if (shape.id === e.src || shape.id === e.tgt) continue;
			if (segsOf[i].some(s => segHitsBox(s, shape))) throughPairs.push({ edge: e.id, shape: shape.id });
		}
	}

	const allSegs = segsOf.flat();
	for (const shape of nodes) {
		if (!shape.label) continue;
		for (const other of nodes) {
			if (other.id !== shape.id && boxesHit(shape.label, other)) labelPairs.push({ label: shape.id, hits: other.id });
		}
		if (allSegs.some(s => segHitsBox(s, shape.label) || boxesHit(shape.label, bboxOf(s)))) {
			labelPairs.push({ label: shape.id, hits: "an edge" });
		}
	}
	for (let i = 0; i < edges.length; i++) {
		const e = edges[i];
		if (!e.label) continue;
		for (const shape of nodes) if (boxesHit(e.label, shape)) labelPairs.push({ label: e.id, hits: shape.id });
		for (let j = 0; j < edges.length; j++) {
			if (j === i) continue;
			if (segsOf[j].some(s => boxesHit(e.label, bboxOf(s)))) { labelPairs.push({ label: e.id, hits: edges[j].id }); break; }
		}
	}

	return {
		crossings: crossingPairs.length,
		overlaps: overlapPairs.length,
		throughShape: throughPairs.length,
		labelCollisions: labelPairs.length,
		crossingPairs, overlapPairs, throughPairs, labelPairs,
	};
}

function bboxOf(seg) {
	const [[ax, ay], [bx, by]] = seg;
	return { x: Math.min(ax, bx), y: Math.min(ay, by), w: Math.max(Math.abs(bx - ax), 1), h: Math.max(Math.abs(by - ay), 1) };
}
