/**
 * Auto-layout for ProsAlly-generated BPMN XML.
 *
 * Parses the XML, builds a directed graph from sequenceFlows, assigns
 * left-to-right column positions via BFS + join-relaxation, then rewrites
 * every BPMNShape bound and BPMNEdge waypoint. Any semantic element that
 * has no DI counterpart gets one created automatically (satisfies no-bpmndi).
 *
 * Nothing outside this file touches bpmn-js internals — pure DOM + serialiser.
 */

// ── Dimensions per BPMN element type ──────────────────────────────────────────
const DIMS = {
	startEvent:             { w: 36,  h: 36  },
	endEvent:               { w: 36,  h: 36  },
	intermediateThrowEvent: { w: 36,  h: 36  },
	intermediateCatchEvent: { w: 36,  h: 36  },
	boundaryEvent:          { w: 36,  h: 36  },
	userTask:               { w: 100, h: 80  },
	serviceTask:            { w: 100, h: 80  },
	scriptTask:             { w: 100, h: 80  },
	manualTask:             { w: 100, h: 80  },
	businessRuleTask:       { w: 100, h: 80  },
	task:                   { w: 100, h: 80  },
	callActivity:           { w: 100, h: 80  },
	subProcess:             { w: 200, h: 120 },
	exclusiveGateway:       { w: 50,  h: 50  },
	parallelGateway:        { w: 50,  h: 50  },
	inclusiveGateway:       { w: 50,  h: 50  },
	eventBasedGateway:      { w: 50,  h: 50  },
};
const DEFAULT_DIMS = { w: 100, h: 80 };

// ── Layout constants ─────────────────────────────────────────────────────────
const H_STEP   = 160;   // horizontal centre-to-centre between columns
const V_STEP   = 120;   // vertical centre-to-centre between rows in a column
const MARGIN_X = 150;   // x-centre of column 0
const CENTER_Y = 300;   // primary vertical midpoint

// ── XML namespace URIs ────────────────────────────────────────────────────────
const BPMN_NS   = "http://www.omg.org/spec/BPMN/20100524/MODEL";
const BPMNDI_NS = "http://www.omg.org/spec/BPMN/20100524/DI";
const DC_NS     = "http://www.omg.org/spec/DD/20100524/DC";
const DI_NS     = "http://www.omg.org/spec/DD/20100524/DI";

function localName(tag) {
	return tag.includes(":") ? tag.split(":")[1] : tag;
}

/**
 * Apply a clean left-to-right layout to a BPMN 2.0 XML string.
 * Returns the relaid-out XML string, or the original string unchanged if
 * the input cannot be parsed.
 *
 * @param {string} xmlString - Raw BPMN 2.0 XML
 * @returns {string} Relaid-out BPMN 2.0 XML
 */
export function layoutBpmnXml(xmlString) {
	const parser = new DOMParser();
	const doc = parser.parseFromString(xmlString, "application/xml");
	if (doc.querySelector("parsererror")) return xmlString;

	const processEl = doc.getElementsByTagNameNS(BPMN_NS, "process")[0];
	if (!processEl) return xmlString;

	const planeEl = doc.getElementsByTagNameNS(BPMNDI_NS, "BPMNPlane")[0];
	if (!planeEl) return xmlString;

	// ── 1. Collect semantic elements ─────────────────────────────────────────
	const nodes    = {};   // id → { type: string }
	const flows    = {};   // flowId → { source, target }
	const outgoing = {};   // nodeId → [targetId, ...]

	for (const child of processEl.children) {
		const type = localName(child.tagName);
		const id   = child.getAttribute("id");
		if (!id) continue;

		if (type === "sequenceFlow") {
			const source = child.getAttribute("sourceRef");
			const target = child.getAttribute("targetRef");
			if (source && target) {
				flows[id] = { source, target };
				(outgoing[source] = outgoing[source] || []).push(target);
			}
		} else {
			nodes[id] = { type };
		}
	}

	if (!Object.keys(nodes).length) return xmlString;

	// ── 2. BFS from start event to seed column assignments ───────────────────
	const startId =
		Object.entries(nodes).find(([, n]) => n.type === "startEvent")?.[0] ||
		Object.keys(nodes)[0];

	const column = { [startId]: 0 };
	const bfsQueue = [startId];
	const bfsSeen  = new Set([startId]);

	while (bfsQueue.length) {
		const curr = bfsQueue.shift();
		for (const next of (outgoing[curr] || [])) {
			if (!bfsSeen.has(next)) {
				bfsSeen.add(next);
				column[next] = (column[curr] ?? 0) + 1;
				bfsQueue.push(next);
			}
		}
	}

	// ── 3. Relax join nodes to the max incoming column + 1 ───────────────────
	// Skips back-edges (source column >= target column) to stay cycle-safe.
	const nodeCount = Object.keys(nodes).length;
	for (let pass = 0; pass < nodeCount; pass++) {
		let changed = false;
		for (const { source, target } of Object.values(flows)) {
			const sc = column[source] ?? 0;
			const tc = column[target] ?? 0;
			if (sc >= tc) continue;          // back-edge — skip
			if (sc + 1 > tc) {
				column[target] = sc + 1;
				changed = true;
			}
		}
		if (!changed) break;
	}

	// Assign column 0 to any node not reached by BFS (disconnected islands)
	for (const id of Object.keys(nodes)) {
		if (column[id] === undefined) column[id] = 0;
	}

	// ── 4. Group by column, assign centre positions ───────────────────────────
	const byColumn = {};
	for (const [id, col] of Object.entries(column)) {
		if (!nodes[id]) continue;
		(byColumn[col] = byColumn[col] || []).push(id);
	}

	const positions = {};   // id → { cx, cy }
	for (const [col, ids] of Object.entries(byColumn)) {
		const cx          = MARGIN_X + parseInt(col) * H_STEP;
		const totalHeight = (ids.length - 1) * V_STEP;
		const startY      = CENTER_Y - totalHeight / 2;
		ids.forEach((id, i) => {
			positions[id] = { cx, cy: startY + i * V_STEP };
		});
	}

	// ── 5. Helpers ────────────────────────────────────────────────────────────
	function getBounds(id) {
		const pos       = positions[id] || { cx: MARGIN_X, cy: CENTER_Y };
		const { w, h }  = DIMS[nodes[id]?.type] || DEFAULT_DIMS;
		return {
			x: Math.round(pos.cx - w / 2),
			y: Math.round(pos.cy - h / 2),
			w,
			h,
		};
	}

	function getWaypoints(flowId) {
		const { source, target } = flows[flowId];
		const sb = getBounds(source);
		const tb = getBounds(target);
		const sx = sb.x + sb.w;
		const sy = sb.y + Math.round(sb.h / 2);
		const tx = tb.x;
		const ty = tb.y + Math.round(tb.h / 2);

		// Back-edge (loop-back): arc above both shapes
		const srcCx = positions[source]?.cx ?? 0;
		const tgtCx = positions[target]?.cx ?? 0;
		if (tgtCx <= srcCx) {
			const topY  = Math.min(sb.y, tb.y) - 50;
			const sMidX = sb.x + Math.round(sb.w / 2);
			const tMidX = tb.x + Math.round(tb.w / 2);
			return [
				{ x: sMidX, y: sb.y },
				{ x: sMidX, y: topY },
				{ x: tMidX, y: topY },
				{ x: tMidX, y: tb.y },
			];
		}

		// Same row — straight connector
		if (Math.abs(sy - ty) <= 2) {
			return [{ x: sx, y: sy }, { x: tx, y: ty }];
		}

		// Different rows — Manhattan L-routing
		const midX = Math.round((sx + tx) / 2);
		return [
			{ x: sx,   y: sy },
			{ x: midX, y: sy },
			{ x: midX, y: ty },
			{ x: tx,   y: ty },
		];
	}

	// ── 6. Update existing BPMNShape bounds ──────────────────────────────────
	const updatedShapes = new Set();
	for (const shape of doc.getElementsByTagNameNS(BPMNDI_NS, "BPMNShape")) {
		const id = shape.getAttribute("bpmnElement");
		if (!id || !positions[id]) continue;
		updatedShapes.add(id);
		const b = getBounds(id);
		let boundsEl = shape.getElementsByTagNameNS(DC_NS, "Bounds")[0];
		if (!boundsEl) {
			boundsEl = doc.createElementNS(DC_NS, "dc:Bounds");
			shape.appendChild(boundsEl);
		}
		boundsEl.setAttribute("x", b.x);
		boundsEl.setAttribute("y", b.y);
		boundsEl.setAttribute("width", b.w);
		boundsEl.setAttribute("height", b.h);
	}

	// ── 7. Create BPMNShape for any node that had none ────────────────────────
	for (const id of Object.keys(nodes)) {
		if (updatedShapes.has(id)) continue;
		const b     = getBounds(id);
		const shape = doc.createElementNS(BPMNDI_NS, "bpmndi:BPMNShape");
		shape.setAttribute("id",          `Shape_${id}`);
		shape.setAttribute("bpmnElement", id);
		const boundsEl = doc.createElementNS(DC_NS, "dc:Bounds");
		boundsEl.setAttribute("x",      b.x);
		boundsEl.setAttribute("y",      b.y);
		boundsEl.setAttribute("width",  b.w);
		boundsEl.setAttribute("height", b.h);
		shape.appendChild(boundsEl);
		planeEl.appendChild(shape);
	}

	// ── 8. Update existing BPMNEdge waypoints ────────────────────────────────
	const updatedEdges = new Set();
	for (const edge of doc.getElementsByTagNameNS(BPMNDI_NS, "BPMNEdge")) {
		const flowId = edge.getAttribute("bpmnElement");
		if (!flowId || !flows[flowId]) continue;
		updatedEdges.add(flowId);
		for (const wp of [...edge.getElementsByTagNameNS(DI_NS, "waypoint")]) {
			wp.remove();
		}
		for (const pt of getWaypoints(flowId)) {
			const wp = doc.createElementNS(DI_NS, "di:waypoint");
			wp.setAttribute("x", pt.x);
			wp.setAttribute("y", pt.y);
			edge.appendChild(wp);
		}
	}

	// ── 9. Create BPMNEdge for any flow that had none ─────────────────────────
	for (const flowId of Object.keys(flows)) {
		if (updatedEdges.has(flowId)) continue;
		const edge = doc.createElementNS(BPMNDI_NS, "bpmndi:BPMNEdge");
		edge.setAttribute("id",          `Edge_${flowId}`);
		edge.setAttribute("bpmnElement", flowId);
		for (const pt of getWaypoints(flowId)) {
			const wp = doc.createElementNS(DI_NS, "di:waypoint");
			wp.setAttribute("x", pt.x);
			wp.setAttribute("y", pt.y);
			edge.appendChild(wp);
		}
		planeEl.appendChild(edge);
	}

	return new XMLSerializer().serializeToString(doc);
}
