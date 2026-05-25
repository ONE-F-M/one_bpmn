#!/usr/bin/env node
/**
 * BPMN IR → XML pipeline.
 *
 * Reads an IR JSON document from stdin, runs three deterministic passes:
 *   1. normalizeGateways   — eliminate task/event fan-out and fan-in
 *   2. assertGatewayPairing — reject mismatched opens/closes pairs before compiling
 *   3. compileIRtoBpmn     — build a bpmn-moddle tree, add DI layout
 *
 * For processes WITHOUT lanes: bpmn-auto-layout adds BPMNDI automatically.
 * For processes WITH lanes (pools): bpmn-auto-layout v0.4.0 does not support
 * Pools, so BPMNDI is generated manually by buildManualLaneDI().
 *
 * Writes { ok, xml, problems:[{kind, message}] } to stdout.
 * Semantic validation is handled by the Python bpmn_validator layer.
 *
 * Invoked by ProsAllyAgent._call_pipeline() via subprocess.
 */

import { BpmnModdle } from 'bpmn-moddle';

// ── Constants ─────────────────────────────────────────────────────────────────

const GATEWAY_TYPES = new Set([
  'exclusiveGateway', 'parallelGateway', 'inclusiveGateway',
]);

const BPMN_TYPE_MAP = {
  startEvent:       'bpmn:StartEvent',
  endEvent:         'bpmn:EndEvent',
  task:             'bpmn:ScriptTask',       // fallback; normalised IR should never emit bare task
  userTask:         'bpmn:UserTask',
  scriptTask:       'bpmn:ScriptTask',
  serviceTask:      'bpmn:ServiceTask',
  manualTask:       'bpmn:ManualTask',
  businessRuleTask: 'bpmn:BusinessRuleTask',
  exclusiveGateway: 'bpmn:ExclusiveGateway',
  parallelGateway:  'bpmn:ParallelGateway',
  inclusiveGateway: 'bpmn:InclusiveGateway',
  subProcess:       'bpmn:SubProcess',
};

// Layout constants for manual lane DI generation
const PARTICIPANT_X    = 150;
const PARTICIPANT_Y    = 80;
const POOL_HEADER_W    = 30;   // vertical pool-name strip (leftmost)
const LANE_HEADER_W    = 30;   // per-lane name strip
const LANE_HEIGHT      = 250;  // pixels per lane row
const COL_STEP         = 170;  // horizontal distance between element columns
const MARGIN_COL_LEFT  = 60;   // padding before column 0
const MARGIN_COL_RIGHT = 100;  // padding after last column

// Per-type element dimensions (pixels)
const NODE_DIMS = {
  startEvent:       { w: 36, h: 36 },
  endEvent:         { w: 36, h: 36 },
  exclusiveGateway: { w: 50, h: 50 },
  parallelGateway:  { w: 50, h: 50 },
  inclusiveGateway: { w: 50, h: 50 },
};
const DEFAULT_NODE_DIMS = { w: 100, h: 80 };

function nodeDims(type) {
  return NODE_DIMS[type] || DEFAULT_NODE_DIMS;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function readStdin() {
  return new Promise((resolve, reject) => {
    let buf = '';
    process.stdin.setEncoding('utf8');
    process.stdin.on('data', chunk => { buf += chunk; });
    process.stdin.on('end',  () => resolve(buf));
    process.stdin.on('error', reject);
  });
}

function buildAdjacency(nodes, flows) {
  const out = new Map(nodes.map(n => [n.id, []]));
  const inn = new Map(nodes.map(n => [n.id, []]));
  for (const f of flows) {
    (out.get(f.from) || []).push(f);
    (inn.get(f.to)   || []).push(f);
  }
  return { out, inn };
}

let _seq = 0;
function uid(prefix) { return `${prefix}_${++_seq}`; }

// ── Pass 1: normalizeGateways ─────────────────────────────────────────────────
//
// Invariant enforced: no non-gateway node has >1 incoming or >1 outgoing flow.
//
//   no-implicit-split (task with >1 outgoing) → insert split gateway after node
//   fake-join         (task with >1 incoming) → insert join  gateway before node
//
// Inserted gateways are tagged { inferred: true } so downstream code can
// distinguish them from explicitly modelled gateways.

function normalizeGateways(ir) {
  let nodes = ir.nodes.map(n => ({ ...n }));
  let flows = ir.flows.map(f => ({ ...f }));

  // ── Fan-out pass ──
  {
    const { out } = buildAdjacency(nodes, flows);
    for (const n of [...nodes]) {
      if (GATEWAY_TYPES.has(n.type)) continue;
      const outFlows = out.get(n.id) || [];
      if (outFlows.length <= 1) continue;

      const gwType = outFlows.some(f => f.condition) ? 'exclusiveGateway' : 'parallelGateway';
      const gwId   = uid('gw_split');
      nodes.push({ id: gwId, type: gwType, name: `${n.name} Split`, inferred: true });

      // Repoint: all flows previously sourced from N now come from the new gateway
      flows = flows.map(f => outFlows.includes(f) ? { ...f, from: gwId } : f);
      // Bridge: N → gateway
      flows.push({ from: n.id, to: gwId });

      // Exclusive split must have exactly one default flow.
      // If all outgoing flows carry conditions (no obvious fallback), strip the last
      // one's condition and promote it to the unconditional default path.
      if (gwType === 'exclusiveGateway') {
        if (!flows.filter(f => f.from === gwId).some(f => f.default)) {
          let di = flows.findIndex(f => f.from === gwId && !f.condition && !f.default);
          const mustStrip = di < 0;
          if (di < 0) di = flows.reduce((best, f, i) => (f.from === gwId ? i : best), -1);
          if (di >= 0) {
            flows = flows.map((f, i) => {
              if (i !== di) return f;
              const f2 = { ...f, default: true };
              if (mustStrip) delete f2.condition;
              return f2;
            });
          }
        }
      }
    }
  }

  // ── Fan-in pass (rebuild adjacency after fan-out changes) ──
  {
    const { inn } = buildAdjacency(nodes, flows);
    for (const n of [...nodes]) {
      if (GATEWAY_TYPES.has(n.type)) continue;
      const inFlows = inn.get(n.id) || [];
      if (inFlows.length <= 1) continue;

      const gwId = uid('gw_join');
      nodes.push({ id: gwId, type: 'exclusiveGateway', name: `${n.name} Join`, inferred: true });

      // Repoint: all flows previously targeting N now target the join gateway
      flows = flows.map(f => inFlows.includes(f) ? { ...f, to: gwId } : f);
      // Bridge: join gateway → N
      flows.push({ from: gwId, to: n.id });
    }
  }

  // ── Gateway join-fork pass (rebuild adjacency after prior passes) ──
  // A gateway with >1 incoming AND >1 outgoing violates no-gateway-join-fork.
  // Fix: keep original as the join (N→1), insert a new fork gateway (1→N).
  {
    const { out, inn } = buildAdjacency(nodes, flows);
    for (const n of [...nodes]) {
      if (!GATEWAY_TYPES.has(n.type)) continue;
      const inFlows  = inn.get(n.id) || [];
      const outFlows = out.get(n.id) || [];
      if (inFlows.length <= 1 || outFlows.length <= 1) continue;

      // If none of the outgoing flows carry conditions or a default, the original gateway
      // had no routing logic — make the fork parallel so all paths run concurrently and
      // no conditional-flows check fires on the inferred fork.
      const forkType = outFlows.some(f => f.condition || f.default) ? n.type : 'parallelGateway';
      const forkId = uid('gw_fork');
      nodes.push({ id: forkId, type: forkType, name: `${n.name} Fork`, inferred: true });

      // All outgoing flows from original now come from the fork gateway
      flows = flows.map(f => outFlows.includes(f) ? { ...f, from: forkId } : f);
      // Bridge: join → fork
      flows.push({ from: n.id, to: forkId });

      // Exclusive fork must have exactly one default flow (same robust logic as fan-out pass).
      if (forkType === 'exclusiveGateway') {
        if (!flows.filter(f => f.from === forkId).some(f => f.default)) {
          let di = flows.findIndex(f => f.from === forkId && !f.condition && !f.default);
          const mustStrip = di < 0;
          if (di < 0) di = flows.reduce((best, f, i) => (f.from === forkId ? i : best), -1);
          if (di >= 0) {
            flows = flows.map((f, i) => {
              if (i !== di) return f;
              const f2 = { ...f, default: true };
              if (mustStrip) delete f2.condition;
              return f2;
            });
          }
        }
      }
    }
  }

  return { ...ir, nodes, flows };
}

// ── Post-normalization structural check ───────────────────────────────────────
//
// After all three normalizeGateways passes, every non-gateway node must have
// at most 1 outgoing and at most 1 incoming flow.  If any remain it means
// normalizeGateways has an unhandled edge case — surface it immediately so the
// Python repair loop can handle it rather than silently producing bad XML.

function assertNoImplicitSplitOrJoin(ir) {
  const problems = [];
  const { out, inn } = buildAdjacency(ir.nodes, ir.flows);
  for (const n of ir.nodes) {
    if (GATEWAY_TYPES.has(n.type)) continue;
    const outCount = (out.get(n.id) || []).length;
    const inCount  = (inn.get(n.id) || []).length;
    if (outCount > 1) {
      problems.push({
        kind: 'lint', rule: 'no-implicit-split', elementId: n.id,
        message: `Node "${n.id}" (${n.type}) still has ${outCount} outgoing flows after normalisation — normalizeGateways bug.`,
      });
    }
    if (inCount > 1) {
      problems.push({
        kind: 'lint', rule: 'fake-join', elementId: n.id,
        message: `Node "${n.id}" (${n.type}) still has ${inCount} incoming flows after normalisation — normalizeGateways bug.`,
      });
    }
  }
  return problems;
}

// ── Pass 2: assertGatewayPairing ──────────────────────────────────────────────
//
// A node with `closes: "<splitId>"` declares it is the join counterpart of that
// split. The types must match: a parallelGateway split must be closed by a
// parallelGateway join. Mismatch passes bpmnlint but deadlocks Spiff at runtime.
// This pass rejects before compiling so the error reaches the LLM repair loop.

function assertGatewayPairing(ir) {
  const problems = [];
  const nodeMap  = new Map(ir.nodes.map(n => [n.id, n]));

  for (const n of ir.nodes) {
    if (!n.closes) continue;
    const split = nodeMap.get(n.closes);
    if (!split) {
      problems.push({
        kind:    'pairing',
        message: `Node "${n.id}" (${n.name}) declares closes="${n.closes}" but that node does not exist.`,
      });
    } else if (split.type !== n.type) {
      problems.push({
        kind:    'pairing',
        message:
          `Gateway pairing mismatch: "${n.id}" (type=${n.type}) closes "${split.id}" (type=${split.type}). ` +
          `A ${split.type} split must be closed by a ${split.type} join, not a ${n.type}.`,
      });
    }
  }

  return problems;
}

// ── Pass 3: compileIRtoBpmn ───────────────────────────────────────────────────
//
// Deterministic: same IR always produces the same moddle tree.
// Stable IDs are used as-is from the IR; flow IDs are derived from source+target+index.
// Incoming/outgoing refs and default pointers are wired exactly once.

async function compileIRtoBpmn(ir) {
  const moddle       = new BpmnModdle();
  const flowElements = [];
  const elementById  = new Map();

  // 1. Semantic nodes
  // Do NOT pass incoming/outgoing arrays — bpmn-moddle auto-wires them through the
  // sourceRef/targetRef inverse associations when it processes the Process flowElements.
  // Passing them AND manually pushing causes each flow to appear twice in the output.
  for (const n of ir.nodes) {
    const bpmnType = BPMN_TYPE_MAP[n.type] || 'bpmn:ScriptTask';
    const el = moddle.create(bpmnType, { id: n.id, name: n.name });
    elementById.set(n.id, el);
    flowElements.push(el);
  }

  // 2. Sequence flows — setting sourceRef/targetRef is sufficient; moddle wires
  // the inverse incoming/outgoing references automatically via its type descriptors.
  const seqMeta = [];
  for (let i = 0; i < ir.flows.length; i++) {
    const f   = ir.flows[i];
    const src = elementById.get(f.from);
    const tgt = elementById.get(f.to);
    if (!src || !tgt) continue;

    const sf = moddle.create('bpmn:SequenceFlow', {
      id:        `flow_${f.from}_${f.to}_${i}`,
      name:      f.name || '',
      sourceRef: src,
      targetRef: tgt,
    });

    if (f.condition) {
      sf.conditionExpression = moddle.create('bpmn:FormalExpression', { body: f.condition });
    }

    flowElements.push(sf);
    seqMeta.push({ sf, f });
  }

  // 3. Wire default flows on exclusive / inclusive gateways
  for (const { sf, f } of seqMeta) {
    if (f.default) {
      const src = elementById.get(f.from);
      if (src) src.default = sf;
    }
  }

  // 4. Lane set (optional) — lanes is [{ id, name, role? }]
  let laneSets;
  if (ir.lanes && ir.lanes.length) {
    const laneEls = ir.lanes.map(lane => {
      const flowNodeRef = (ir.nodes || [])
        .filter(n => n.lane === lane.id)
        .map(n => elementById.get(n.id))
        .filter(Boolean);
      return moddle.create('bpmn:Lane', { id: lane.id, name: lane.name, flowNodeRef });
    });
    laneSets = [moddle.create('bpmn:LaneSet', { id: 'LaneSet_1', lanes: laneEls })];
  }

  // 5. Process
  const processEl = moddle.create('bpmn:Process', {
    id:           'Process_1',
    isExecutable: true,
    flowElements,
    ...(laneSets ? { laneSets } : {}),
  });

  // 6. Collaboration + Participant (required for bpmn-js to render swim lanes)
  const rootElements = [processEl];
  if (laneSets) {
    const participantEl = moddle.create('bpmn:Participant', {
      id:         'Participant_1',
      name:       ir.name || 'Process',
      processRef: processEl,
    });
    const collaborationEl = moddle.create('bpmn:Collaboration', {
      id:           'Collaboration_1',
      participants: [participantEl],
    });
    rootElements.unshift(collaborationEl);  // collaboration must come first
  }

  const definitions = moddle.create('bpmn:Definitions', {
    id:              'Definitions_1',
    targetNamespace: 'http://bpmn.io/schema/bpmn',
    exporter:        'processa-pipeline',
    exporterVersion: '1.0',
    rootElements,
  });

  const { xml } = await moddle.toXML(definitions, { format: true });
  return xml;
}

// ── Manual DI builder for lane-based processes ────────────────────────────────
//
// bpmn-auto-layout v0.4.0 explicitly does not support Pools.
// When ir.lanes is present we skip auto-layout and generate BPMNDI ourselves.
//
// Algorithm:
//   1. Propagate lane assignments to inferred gateways (no explicit lane field)
//   2. Topological column assignment: longest-path BFS so elements flow left→right
//   3. Within each (lane, column) cell, stack elements vertically
//   4. Emit BPMNDiagram XML: participant → lanes → node shapes → edge waypoints

function buildManualLaneDI(ir) {
  const lanes = ir.lanes || [];   // [{ id, name, role? }]
  if (!lanes.length) return '';

  const laneIndexById = new Map(lanes.map((l, i) => [l.id, i]));
  const nodeMap       = new Map(ir.nodes.map(n => [n.id, n]));

  // Build adjacency for lane propagation and column assignment
  const adjOut = new Map(ir.nodes.map(n => [n.id, []]));
  const adjInn = new Map(ir.nodes.map(n => [n.id, []]));
  for (const f of ir.flows) {
    if (adjOut.has(f.from)) adjOut.get(f.from).push(f.to);
    if (adjInn.has(f.to))   adjInn.get(f.to).push(f.from);
  }

  // Propagate lane id to inferred gateways (no explicit lane field).
  // Iterates until stable so multi-hop chains resolve correctly.
  const nodeLaneId = new Map();
  for (const n of ir.nodes) {
    if (n.lane) nodeLaneId.set(n.id, n.lane);
  }
  let changed = true;
  while (changed) {
    changed = false;
    for (const n of ir.nodes) {
      if (nodeLaneId.has(n.id)) continue;
      const neighbours = (adjInn.get(n.id) || []).concat(adjOut.get(n.id) || []);
      for (const nb of neighbours) {
        if (nodeLaneId.has(nb)) {
          nodeLaneId.set(n.id, nodeLaneId.get(nb));
          changed = true;
          break;
        }
      }
    }
  }
  // Final fallback: unresolved nodes go to first lane
  for (const n of ir.nodes) {
    if (!nodeLaneId.has(n.id) && lanes.length) nodeLaneId.set(n.id, lanes[0].id);
  }

  // Column assignment: longest-path DP via Kahn's topological order
  const inDeg = new Map(ir.nodes.map(n => [n.id, 0]));
  for (const f of ir.flows) {
    if (inDeg.has(f.to)) inDeg.set(f.to, (inDeg.get(f.to) || 0) + 1);
  }
  const col   = new Map();
  const queue = [];
  for (const n of ir.nodes) {
    if (inDeg.get(n.id) === 0) { queue.push(n.id); col.set(n.id, 0); }
  }
  let qi = 0;
  while (qi < queue.length) {
    const id = queue[qi++];
    const c  = col.get(id) || 0;
    for (const succId of (adjOut.get(id) || [])) {
      const newC = c + 1;
      if (!col.has(succId) || col.get(succId) < newC) col.set(succId, newC);
      const deg = (inDeg.get(succId) || 1) - 1;
      inDeg.set(succId, deg);
      if (deg === 0) queue.push(succId);
    }
  }
  for (const n of ir.nodes) { if (!col.has(n.id)) col.set(n.id, 0); }

  const maxCol = ir.nodes.reduce((m, n) => Math.max(m, col.get(n.id) || 0), 0);

  // Group nodes by (laneIdx, col) cell for vertical stacking
  const groups = new Map();  // key "li:c" → { li, c, nodeIds[] }
  for (const n of ir.nodes) {
    const lid = nodeLaneId.get(n.id) || lanes[0].id;
    const li  = laneIndexById.has(lid) ? laneIndexById.get(lid) : 0;
    const c   = col.get(n.id) || 0;
    const k   = li + ':' + c;
    if (!groups.has(k)) groups.set(k, { li, c, nodeIds: [] });
    groups.get(k).nodeIds.push(n.id);
  }

  // Busiest-column height per lane: tallest cell drives the band height.
  // Minimum height is LANE_HEIGHT (default for empty or uncrowded lanes).
  const ROW_H = 100;  // height allocated per node within a band column
  const laneH = lanes.map((_, li) => {
    let maxStack = 0;
    for (const grp of groups.values()) {
      if (grp.li === li) maxStack = Math.max(maxStack, grp.nodeIds.length);
    }
    return Math.max(LANE_HEIGHT, maxStack * ROW_H);
  });

  // Cumulative Y offsets for each lane band (bands tile contiguously)
  const laneTopY = [];
  let yOff = PARTICIPANT_Y;
  for (let i = 0; i < lanes.length; i++) {
    laneTopY.push(yOff);
    yOff += laneH[i];
  }
  const totalH = yOff - PARTICIPANT_Y;

  const contentW     = MARGIN_COL_LEFT + maxCol * COL_STEP + MARGIN_COL_RIGHT;
  const participantW = POOL_HEADER_W + LANE_HEADER_W + contentW;

  // Compute pixel-precise position for every node
  const nodePos = new Map();  // nodeId → { x, y, w, h }
  for (const grp of groups.values()) {
    const centerX = PARTICIPANT_X + POOL_HEADER_W + LANE_HEADER_W + MARGIN_COL_LEFT + grp.c * COL_STEP;
    const bandTop = laneTopY[grp.li];
    const bandH   = laneH[grp.li];
    const slotH   = bandH / grp.nodeIds.length;
    for (let i = 0; i < grp.nodeIds.length; i++) {
      const nid = grp.nodeIds[i];
      const n   = nodeMap.get(nid);
      const d   = nodeDims(n.type);
      const slotCY = bandTop + slotH * i + slotH / 2;
      nodePos.set(nid, {
        x: Math.round(centerX - d.w / 2),
        y: Math.round(slotCY  - d.h / 2),
        w: d.w,
        h: d.h,
      });
    }
  }

  // ── Serialise BPMNDI XML ──────────────────────────────────────────────────────
  const lines = [];
  lines.push('  <bpmndi:BPMNDiagram id="BPMNDiagram_1">');
  lines.push('    <bpmndi:BPMNPlane id="BPMNPlane_1" bpmnElement="Collaboration_1">');

  // Participant (pool) shape
  lines.push('      <bpmndi:BPMNShape id="Participant_1_di" bpmnElement="Participant_1" isHorizontal="true">');
  lines.push('        <dc:Bounds x="' + PARTICIPANT_X + '" y="' + PARTICIPANT_Y +
             '" width="' + participantW + '" height="' + totalH + '" />');
  lines.push('      </bpmndi:BPMNShape>');

  // Lane shapes — bands tile exactly (heights sum to pool inner height)
  for (let i = 0; i < lanes.length; i++) {
    const lane = lanes[i];
    const laneX = PARTICIPANT_X + POOL_HEADER_W;
    const laneW = participantW - POOL_HEADER_W;
    lines.push('      <bpmndi:BPMNShape id="' + lane.id + '_di" bpmnElement="' + lane.id + '" isHorizontal="true">');
    lines.push('        <dc:Bounds x="' + laneX + '" y="' + laneTopY[i] +
               '" width="' + laneW + '" height="' + laneH[i] + '" />');
    lines.push('      </bpmndi:BPMNShape>');
  }

  // Node shapes
  for (const n of ir.nodes) {
    const pos = nodePos.get(n.id);
    if (!pos) continue;
    const isCompact = (n.type === 'startEvent' || n.type === 'endEvent' || GATEWAY_TYPES.has(n.type));
    lines.push('      <bpmndi:BPMNShape id="' + n.id + '_di" bpmnElement="' + n.id + '">');
    lines.push('        <dc:Bounds x="' + pos.x + '" y="' + pos.y +
               '" width="' + pos.w + '" height="' + pos.h + '" />');
    if (isCompact) {
      const lblX = Math.round(pos.x + pos.w / 2 - 25);
      const lblY = pos.y + pos.h + 2;
      lines.push('        <bpmndi:BPMNLabel>');
      lines.push('          <dc:Bounds x="' + lblX + '" y="' + lblY + '" width="50" height="14" />');
      lines.push('        </bpmndi:BPMNLabel>');
    }
    lines.push('      </bpmndi:BPMNShape>');
  }

  // Sequence flow edges — right-centre of source → left-centre of target
  for (let i = 0; i < ir.flows.length; i++) {
    const f   = ir.flows[i];
    const src = nodePos.get(f.from);
    const tgt = nodePos.get(f.to);
    if (!src || !tgt) continue;
    const flowId = 'flow_' + f.from + '_' + f.to + '_' + i;
    lines.push('      <bpmndi:BPMNEdge id="' + flowId + '_di" bpmnElement="' + flowId + '">');
    lines.push('        <di:waypoint x="' + (src.x + src.w) + '" y="' + Math.round(src.y + src.h / 2) + '" />');
    lines.push('        <di:waypoint x="' + tgt.x            + '" y="' + Math.round(tgt.y + tgt.h / 2) + '" />');
    lines.push('      </bpmndi:BPMNEdge>');
  }

  lines.push('    </bpmndi:BPMNPlane>');
  lines.push('  </bpmndi:BPMNDiagram>');
  return lines.join('\n');
}

// Inject BPMNDI section + required namespace declarations into moddle-generated XML.
// moddle omits bpmndi/dc/di namespaces when no DI elements exist in the model tree.
function injectLaneDI(xml, diSection) {
  let result = xml;
  if (result.indexOf('xmlns:bpmndi=') === -1) {
    result = result.replace(
      /(<bpmn:definitions)(\s)/,
      '$1' +
      ' xmlns:bpmndi="http://www.omg.org/spec/BPMN/20100524/DI"' +
      ' xmlns:dc="http://www.omg.org/spec/DD/20100524/DC"' +
      ' xmlns:di="http://www.omg.org/spec/DD/20100524/DI"' +
      '$2'
    );
  }
  return result.replace('</bpmn:definitions>', diSection + '\n</bpmn:definitions>');
}

// ── Auto-layout (adds BPMNDI for non-lane processes) ─────────────────────────

async function addAutoLayout(xml) {
  try {
    const mod = await import('bpmn-auto-layout');
    const layoutProcess = mod.layoutProcess || (mod.default && mod.default.layoutProcess);
    if (typeof layoutProcess === 'function') return await layoutProcess(xml);
    // Older API: new BpmnAutoLayout().layout(xml)
    const BpmnAutoLayout = mod.default || mod;
    const { xml: laid } = await new BpmnAutoLayout().layout(xml);
    return laid;
  } catch {
    // bpmn-auto-layout not available; Python validator will report no-bpmndi if DI is missing.
    return xml;
  }
}

// ── Main ──────────────────────────────────────────────────────────────────────

async function main() {
  let ir;
  try {
    ir = JSON.parse(await readStdin());
  } catch (err) {
    process.stdout.write(JSON.stringify({
      ok: false, xml: '',
      problems: [{ kind: 'parse', message: `IR JSON parse error: ${err.message}` }],
    }));
    return;
  }

  // Pass 1 — normalise (deterministic; no LLM involvement)
  const normIR = normalizeGateways(ir);

  // Guard: normalisation must eliminate all non-gateway fan-in / fan-out.
  // If any remain it is a pipeline bug — surface it so the repair loop handles it.
  const structProblems = assertNoImplicitSplitOrJoin(normIR);
  if (structProblems.length) {
    process.stdout.write(JSON.stringify({ ok: false, xml: '', problems: structProblems, normalizedIR: normIR }));
    return;
  }

  // Pass 2 — pairing failures are structural; stop before compiling bad IR
  const pairingProblems = assertGatewayPairing(normIR);
  if (pairingProblems.length) {
    process.stdout.write(JSON.stringify({ ok: false, xml: '', problems: pairingProblems, normalizedIR: normIR }));
    return;
  }

  // Pass 3 — compile to BPMN XML + add layout DI
  let xml;
  try {
    xml = await compileIRtoBpmn(normIR);
    if (normIR.lanes && normIR.lanes.length) {
      // bpmn-auto-layout does not support Pools; generate DI manually
      const diSection = buildManualLaneDI(normIR);
      xml = injectLaneDI(xml, diSection);
    } else {
      xml = await addAutoLayout(xml);
    }
  } catch (err) {
    process.stdout.write(JSON.stringify({
      ok: false, xml: '',
      problems: [{ kind: 'compile', message: `Compile error: ${err.message}` }],
    }));
    return;
  }

  // Semantic validation is handled by the Python bpmn_validator layer after this step.
  // normalizedIR is returned so the repair loop can show the LLM the complete structure
  // (including compiler-inferred gateways) when asking for corrections.
  process.stdout.write(JSON.stringify({ ok: true, xml, problems: [], normalizedIR: normIR }));
}

main().catch(err => {
  process.stdout.write(JSON.stringify({
    ok: false, xml: '',
    problems: [{ kind: 'fatal', message: err.message }],
  }));
  process.exit(1);
});
