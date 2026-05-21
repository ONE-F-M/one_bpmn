/**
 * Auto-layout for ProsAlly-generated BPMN XML.
 *
 * Two problems this function must solve:
 *
 * 1. CONNECTIVITY (no-disconnected / no-implicit-start / no-implicit-end)
 *    bpmn-js moddle populates FlowNode.incoming / .outgoing from
 *    <bpmn:incoming> / <bpmn:outgoing> child elements, NOT from
 *    sequenceFlow sourceRef/targetRef. The LLM never emits those child
 *    elements, so every node looks disconnected to bpmnlint even though
 *    arrows render correctly. Fix: inject the child elements via DOM after
 *    parsing, then serialise only the <bpmn:process> element.
 *
 * 2. DI NAMESPACE (no-bpmndi)
 *    XMLSerializer can reassign namespace prefixes on newly-created elements,
 *    breaking bpmn-moddle reference resolution. Fix: build the entire
 *    <bpmndi:BPMNDiagram> section as a plain string with hard-coded prefixes —
 *    XMLSerializer never touches it.
 *
 * Output strategy
 *   [xml decl from original] +
 *   [<bpmn:definitions …> opening tag from original] +
 *   [XMLSerializer(<bpmn:process> with injected incoming/outgoing)] +
 *   [string-built DI section] +
 *   [</bpmn:definitions>]
 */

// ── Element dimensions ────────────────────────────────────────────────────────
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

// ── Layout constants ──────────────────────────────────────────────────────────
const H_STEP   = 160;
const V_STEP   = 120;
const MARGIN_X = 150;
const CENTER_Y = 300;

const BPMN_NS = "http://www.omg.org/spec/BPMN/20100524/MODEL";

function localName(tag) {
	return tag.includes(":") ? tag.split(":")[1] : tag;
}

export function layoutBpmnXml(xmlString) {
	// ── 1. Parse (read + write for semantic section) ──────────────────────────
	const parser = new DOMParser();
	const doc    = parser.parseFromString(xmlString, "application/xml");
	if (doc.querySelector("parsererror")) return xmlString;

	const processEl = doc.getElementsByTagNameNS(BPMN_NS, "process")[0];
	if (!processEl) return xmlString;

	const processId = processEl.getAttribute("id") || "Process_1";

	// ── 2. Collect nodes, flows, and DOM element references ───────────────────
	const nodes        = {};   // id → { type }
	const nodeElements = {};   // id → DOM element  (for incoming/outgoing injection)
	const flows        = {};   // flowId → { source, target }
	const outgoing     = {};   // nodeId → [targetId, ...]

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
			nodes[id]        = { type };
			nodeElements[id] = child;
		}
	}

	if (!Object.keys(nodes).length) return xmlString;

	// ── 3. Inject <bpmn:incoming> / <bpmn:outgoing> child elements ───────────
	// bpmn-moddle populates FlowNode.incoming/.outgoing from these child
	// elements, not from sequenceFlow sourceRef/targetRef. Without them,
	// no-disconnected / no-implicit-start / no-implicit-end all fire.
	for (const [flowId, { source, target }] of Object.entries(flows)) {
		if (nodeElements[source]) {
			const el = doc.createElementNS(BPMN_NS, "bpmn:outgoing");
			el.textContent = flowId;
			nodeElements[source].appendChild(el);
		}
		if (nodeElements[target]) {
			const el = doc.createElementNS(BPMN_NS, "bpmn:incoming");
			el.textContent = flowId;
			nodeElements[target].appendChild(el);
		}
	}

	// ── 4. BFS from start event ───────────────────────────────────────────────
	const startId =
		Object.entries(nodes).find(([, n]) => n.type === "startEvent")?.[0] ||
		Object.keys(nodes)[0];

	const column   = { [startId]: 0 };
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

	// ── 5. Relax join nodes ───────────────────────────────────────────────────
	const nodeCount = Object.keys(nodes).length;
	for (let pass = 0; pass < nodeCount; pass++) {
		let changed = false;
		for (const { source, target } of Object.values(flows)) {
			const sc = column[source] ?? 0;
			const tc = column[target] ?? 0;
			if (sc >= tc) continue;
			if (sc + 1 > tc) { column[target] = sc + 1; changed = true; }
		}
		if (!changed) break;
	}

	for (const id of Object.keys(nodes)) {
		if (column[id] === undefined) column[id] = 0;
	}

	// ── 6. Assign positions ───────────────────────────────────────────────────
	const byColumn = {};
	for (const [id, col] of Object.entries(column)) {
		if (!nodes[id]) continue;
		(byColumn[col] = byColumn[col] || []).push(id);
	}

	const positions = {};
	for (const [col, ids] of Object.entries(byColumn)) {
		const cx          = MARGIN_X + parseInt(col) * H_STEP;
		const totalHeight = (ids.length - 1) * V_STEP;
		const startY      = CENTER_Y - totalHeight / 2;
		ids.forEach((id, i) => { positions[id] = { cx, cy: startY + i * V_STEP }; });
	}

	// ── 7. Geometry helpers ───────────────────────────────────────────────────
	function getBounds(id) {
		const pos      = positions[id] || { cx: MARGIN_X, cy: CENTER_Y };
		const { w, h } = DIMS[nodes[id]?.type] || DEFAULT_DIMS;
		return { x: Math.round(pos.cx - w / 2), y: Math.round(pos.cy - h / 2), w, h };
	}

	// outgoingIndex: which outgoing slot this flow occupies from its source
	// (used to stagger parallel flows so they don't draw on top of each other)
	const sourceFlowIndex = {};
	for (const [flowId, { source }] of Object.entries(flows)) {
		sourceFlowIndex[flowId] = (sourceFlowIndex[source] = (sourceFlowIndex[source] ?? -1) + 1,
			sourceFlowIndex[source]);
	}
	// Rebuild cleanly
	const _slotCounter = {};
	for (const flowId of Object.keys(flows)) {
		const src = flows[flowId].source;
		_slotCounter[src] = (_slotCounter[src] ?? 0);
		sourceFlowIndex[flowId] = _slotCounter[src]++;
	}

	function getWaypoints(flowId) {
		const { source, target } = flows[flowId];
		const sb  = getBounds(source);
		const tb  = getBounds(target);
		const sx  = sb.x + sb.w;
		const sy  = sb.y + Math.round(sb.h / 2);
		const tx  = tb.x;
		const ty  = tb.y + Math.round(tb.h / 2);
		const idx = sourceFlowIndex[flowId] ?? 0;

		const srcCx = positions[source]?.cx ?? 0;
		const tgtCx = positions[target]?.cx ?? 0;

		// Back-edge: arc above, staggered by flow index to avoid overlap
		if (tgtCx <= srcCx) {
			const topY  = Math.min(sb.y, tb.y) - 50 - idx * 24;
			const sMidX = sb.x + Math.round(sb.w / 2);
			const tMidX = tb.x + Math.round(tb.w / 2);
			return [
				{ x: sMidX, y: sb.y  },
				{ x: sMidX, y: topY  },
				{ x: tMidX, y: topY  },
				{ x: tMidX, y: tb.y  },
			];
		}

		// Same row — straight connector
		if (Math.abs(sy - ty) <= 2) return [{ x: sx, y: sy }, { x: tx, y: ty }];

		// Different rows — Manhattan L-routing.
		// Stagger the vertical turn point by flow index so parallel outgoing flows
		// from the same source don't draw on the same horizontal segment.
		const stagger = idx * 14;
		const midX    = Math.round((sx + tx) / 2) + stagger;
		return [
			{ x: sx,   y: sy },
			{ x: midX, y: sy },
			{ x: midX, y: ty },
			{ x: tx,   y: ty },
		];
	}

	// ── 8. Build DI section as a plain string (no XMLSerializer) ─────────────
	const shapeLines = Object.keys(nodes).map((id) => {
		const b      = getBounds(id);
		const marker = nodes[id]?.type === "exclusiveGateway" ? ' isMarkerVisible="true"' : "";
		return (
			`    <bpmndi:BPMNShape id="Shape_${id}" bpmnElement="${id}"${marker}>\n` +
			`      <dc:Bounds x="${b.x}" y="${b.y}" width="${b.w}" height="${b.h}" />\n` +
			`    </bpmndi:BPMNShape>`
		);
	});

	const edgeLines = Object.keys(flows).map((flowId) => {
		const wps = getWaypoints(flowId)
			.map(pt => `      <di:waypoint x="${pt.x}" y="${pt.y}" />`)
			.join("\n");
		return (
			`    <bpmndi:BPMNEdge id="Edge_${flowId}" bpmnElement="${flowId}">\n` +
			`${wps}\n` +
			`    </bpmndi:BPMNEdge>`
		);
	});

	const diSection =
		`  <bpmndi:BPMNDiagram id="BPMNDiagram_1"\n` +
		`    xmlns:bpmndi="http://www.omg.org/spec/BPMN/20100524/DI">\n` +
		`    <bpmndi:BPMNPlane id="BPMNPlane_1" bpmnElement="${processId}">\n` +
		shapeLines.join("\n") + "\n" +
		edgeLines.join("\n") + "\n" +
		`    </bpmndi:BPMNPlane>\n` +
		`  </bpmndi:BPMNDiagram>`;

	// ── 9. Assemble final XML ─────────────────────────────────────────────────
	// Keep the original XML declaration and <bpmn:definitions ...> opening tag
	// verbatim (preserves all namespace declarations). Replace only the process
	// body (now with injected incoming/outgoing) and the DI section.

	const xmlDeclMatch = xmlString.match(/^<\?xml[^?]*\?>/);
	const xmlDecl      = xmlDeclMatch ? xmlDeclMatch[0] + "\n" : "";

	const defOpenMatch = xmlString.match(/<[a-zA-Z0-9]*:?definitions[^>]*>/);
	const defOpen      = defOpenMatch
		? defOpenMatch[0]
		: `<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL" ` +
		  `xmlns:bpmndi="http://www.omg.org/spec/BPMN/20100524/DI" ` +
		  `xmlns:dc="http://www.omg.org/spec/DD/20100524/DC" ` +
		  `xmlns:di="http://www.omg.org/spec/DD/20100524/DI" ` +
		  `id="Definitions_1" targetNamespace="http://bpmn.io/schema/bpmn">`;

	const defCloseMatch = xmlString.match(/<\/[a-zA-Z0-9]*:?definitions\s*>/);
	const defClose      = defCloseMatch ? defCloseMatch[0] : "</bpmn:definitions>";

	// Serialise only the modified <bpmn:process> element.
	// XMLSerializer may add a redundant xmlns:bpmn on the process tag — that is
	// valid XML and bpmn-moddle handles it correctly via namespace-URI lookup.
	const processXml = new XMLSerializer().serializeToString(processEl);

	return `${xmlDecl}${defOpen}\n${processXml}\n${diSection}\n${defClose}`;
}
