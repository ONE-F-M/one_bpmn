#!/usr/bin/env node
/**
 * BPMN IR → XML pipeline.
 *
 * Reads an IR JSON document from stdin, runs three deterministic passes:
 *   1. normalizeGateways   — eliminate task/event fan-out and fan-in
 *   2. assertGatewayPairing — reject mismatched opens/closes pairs before compiling
 *   3. compileIRtoBpmn     — build a bpmn-moddle tree, run bpmn-auto-layout for DI
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

      // Exclusive split must have exactly one default flow
      if (gwType === 'exclusiveGateway') {
        const gwOut = flows.filter(f => f.from === gwId);
        if (!gwOut.some(f => f.default)) {
          const idx = flows.findIndex(f => f.from === gwId && !f.condition && !f.default);
          if (idx >= 0) flows = flows.map((f, i) => i === idx ? { ...f, default: true } : f);
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

  return { ...ir, nodes, flows };
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
  for (const n of ir.nodes) {
    const bpmnType = BPMN_TYPE_MAP[n.type] || 'bpmn:ScriptTask';
    const el = moddle.create(bpmnType, { id: n.id, name: n.name, incoming: [], outgoing: [] });
    elementById.set(n.id, el);
    flowElements.push(el);
  }

  // 2. Sequence flows
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

    src.outgoing.push(sf);
    tgt.incoming.push(sf);
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

  // 4. Lane set (optional)
  let laneSets;
  if (ir.lanes && ir.lanes.length) {
    const laneEls = ir.lanes.map((laneName, idx) => {
      const flowNodeRef = (ir.nodes || [])
        .filter(n => n.lane === laneName)
        .map(n => elementById.get(n.id))
        .filter(Boolean);
      return moddle.create('bpmn:Lane', { id: `lane_${idx}`, name: laneName, flowNodeRef });
    });
    laneSets = [moddle.create('bpmn:LaneSet', { id: 'LaneSet_1', lanes: laneEls })];
  }

  // 5. Process + Definitions
  const processEl = moddle.create('bpmn:Process', {
    id:           'Process_1',
    isExecutable: true,
    flowElements,
    ...(laneSets ? { laneSets } : {}),
  });

  const definitions = moddle.create('bpmn:Definitions', {
    id:              'Definitions_1',
    targetNamespace: 'http://bpmn.io/schema/bpmn',
    exporter:        'processa-pipeline',
    exporterVersion: '1.0',
    rootElements:    [processEl],
  });

  const { xml } = await moddle.toXML(definitions, { format: true });
  return xml;
}

// ── Auto-layout (adds BPMNDI) ─────────────────────────────────────────────────

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

  // Pass 2 — pairing failures are structural; stop before compiling bad IR
  const pairingProblems = assertGatewayPairing(normIR);
  if (pairingProblems.length) {
    process.stdout.write(JSON.stringify({ ok: false, xml: '', problems: pairingProblems }));
    return;
  }

  // Pass 3 — compile to BPMN XML + add layout DI
  let xml;
  try {
    xml = await compileIRtoBpmn(normIR);
    xml = await addAutoLayout(xml);
  } catch (err) {
    process.stdout.write(JSON.stringify({
      ok: false, xml: '',
      problems: [{ kind: 'compile', message: `Compile error: ${err.message}` }],
    }));
    return;
  }

  // Semantic validation is handled by the Python bpmn_validator layer after this step.
  process.stdout.write(JSON.stringify({ ok: true, xml, problems: [] }));
}

main().catch(err => {
  process.stdout.write(JSON.stringify({
    ok: false, xml: '',
    problems: [{ kind: 'fatal', message: err.message }],
  }));
  process.exit(1);
});
