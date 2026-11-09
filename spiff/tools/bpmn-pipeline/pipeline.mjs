#!/usr/bin/env node
/**
 * BPMN IR → XML pipeline.
 *
 * Reads an IR JSON document from stdin and chains one module per step:
 *   normalise.mjs     - eliminate task/event fan-out and fan-in, reject
 *                       mismatched opens/closes pairs
 *   lanes.mjs         - lane assignment checks, lane propagation, lane set
 *   subprocesses.mjs  - sub-process scopes, their normalisation, box sizing
 *                       and extra planes
 *   layout.mjs        - grid layout, edge routing, BPMNDI, layout audit
 *   compile.mjs       - bpmn-moddle tree → XML, BPMNDI injection
 *   shared.mjs        - constants and helpers used by more than one step
 *
 * This file holds no step logic of its own: it reads the IR, calls the steps in
 * order, and writes { ok, xml, problems:[{kind, message}] } to stdout.
 * Semantic validation is handled by the Python ProsAlly validator (definitions/prosally/validators.py).
 *
 * Invoked from definitions/prosally/tools_pipeline.compile_ir() via subprocess.
 */

import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { compileIRtoBpmn, injectLaneDI } from './compile.mjs';
import { assertLaneAssignment } from './lanes.mjs';
import { auditLayout, buildManualLaneDI } from './layout.mjs';
import { assertGatewayPairing, assertNoImplicitSplitOrJoin, normalizeGateways } from './normalise.mjs';
import {
  assertSubProcessScopes, buildSubProcessPlanes, normaliseSubProcesses, sizeExpandedSubProcesses,
} from './subprocesses.mjs';

function readStdin() {
  return new Promise((resolve, reject) => {
    let buf = '';
    process.stdin.setEncoding('utf8');
    process.stdin.on('data', chunk => { buf += chunk; });
    process.stdin.on('end',  () => resolve(buf));
    process.stdin.on('error', reject);
  });
}

// ── Main ─────────────────────────────────────────────────────────────────────

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

  // Guard: the IR must carry node/flow arrays before any pass touches them.
  // A malformed IR (e.g. LLM returned partial JSON, or omitted a key) would
  // otherwise crash normalizeGateways with "Cannot read properties of
  // undefined (reading 'map')". Report it as a structured problem so the
  // repair loop can ask the LLM to regenerate rather than dying fatally.
  const shapeProblems = [];
  if (!ir || typeof ir !== 'object') {
    shapeProblems.push({ kind: 'parse', message: 'IR is not an object' });
  } else {
    if (!Array.isArray(ir.nodes)) {
      shapeProblems.push({ kind: 'parse', message: 'IR is missing a "nodes" array' });
    }
    if (!Array.isArray(ir.flows)) {
      shapeProblems.push({ kind: 'parse', message: 'IR is missing a "flows" array' });
    }
  }
  if (shapeProblems.length) {
    process.stdout.write(JSON.stringify({ ok: false, xml: '', problems: shapeProblems }));
    return;
  }

  // Pass 1 — normalise (deterministic; no LLM involvement)
  const scopeProblems = assertSubProcessScopes(ir);
  if (scopeProblems.length) {
    process.stdout.write(JSON.stringify({ ok: false, xml: '', problems: scopeProblems }));
    return;
  }
  const normTop = normalizeGateways(ir);
  const { ir: normIR, problems: subProblems } = normaliseSubProcesses(normTop);
  if (subProblems.length) {
    process.stdout.write(JSON.stringify({ ok: false, xml: '', problems: subProblems, normalizedIR: normIR }));
    return;
  }

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

  // Lane structural checks — must pass before compilation so the repair loop
  // can ask the LLM to fix missing or invalid lane assignments.
  if (normIR.lanes && normIR.lanes.length) {
    const laneProblems = assertLaneAssignment(normIR);
    if (laneProblems.length) {
      process.stdout.write(JSON.stringify({ ok: false, xml: '', problems: laneProblems, normalizedIR: normIR }));
      return;
    }
  }

  // Pass 3 — compile to BPMN XML + add layout DI.
  // Every diagram goes through the same builder. A lane-less IR is laid out on
  // one hidden lane with no pool drawn; bpmn-auto-layout, which used to take
  // that case, produced 59 crossings on a 47-node map.
  let xml;
  try {
    xml = await compileIRtoBpmn(normIR);
    const hasLanes = !!(normIR.lanes && normIR.lanes.length);
    const sizeProblems = [];
    const sizedIR = sizeExpandedSubProcesses(normIR, sizeProblems);
    if (sizeProblems.length) {
      process.stdout.write(JSON.stringify({ ok: false, xml: '', problems: sizeProblems, normalizedIR: normIR }));
      return;
    }
    const gridIR = hasLanes ? sizedIR : {
      ...sizedIR,
      lanes: [{ id: '__lane', name: normIR.name || 'Process' }],
      nodes: sizedIR.nodes.map(n => ({ ...n, lane: '__lane' })),
    };
    // buildManualLaneDI also validates Y-bounds and returns problems on failure.
    const { diSection, problems: diProblems } = buildManualLaneDI(gridIR, { pool: hasLanes });
    if (diProblems.length) {
      process.stdout.write(JSON.stringify({ ok: false, xml: '', problems: diProblems, normalizedIR: normIR }));
      return;
    }
    const subPlanes = buildSubProcessPlanes(normIR);
    if (subPlanes.problems.length) {
      process.stdout.write(JSON.stringify({ ok: false, xml: '', problems: subPlanes.problems, normalizedIR: normIR }));
      return;
    }
    xml = injectLaneDI(xml, [diSection, ...subPlanes.sections].join('\n'));
  } catch (err) {
    process.stdout.write(JSON.stringify({
      ok: false, xml: '',
      problems: [{ kind: 'compile', message: `Compile error: ${err.message}` }],
    }));
    return;
  }

  // Measure the drawing. These are reported, not fatal: the XML is valid and
  // executable either way. Crossings are judged on the Python side against the
  // graph's planarity, which decides whether zero or one is the floor.
  const layout = auditLayout(xml);
  const problems = [];
  if (layout.throughShape) problems.push({ kind: 'layout', rule: 'edge-through-shape', elementId: '',
    message: layout.throughShape + ' line(s) pass through a shape they do not connect: ' + JSON.stringify(layout.throughPairs.slice(0, 5)) });
  if (layout.overlaps) problems.push({ kind: 'layout', rule: 'collinear-overlap', elementId: '',
    message: layout.overlaps + ' pair(s) of lines run on top of each other.' });
  if (layout.labelCollisions) problems.push({ kind: 'layout', rule: 'label-collision', elementId: '',
    message: layout.labelCollisions + ' label(s) sit on a shape or a line.' });

  // Semantic validation is handled by the Python ProsAlly validator (definitions/prosally/validators.py) after this step.
  // normalizedIR is returned so the repair loop can show the LLM the complete structure
  // (including compiler-inferred gateways) when asking for corrections.
  process.stdout.write(JSON.stringify({ ok: true, xml, problems, normalizedIR: normIR, layout }));
}

// Run as a program when invoked directly; importable (for tests) otherwise.
if (process.argv[1] && fileURLToPath(import.meta.url) === path.resolve(process.argv[1])) {
  main().catch(err => {
    process.stdout.write(JSON.stringify({
      ok: false, xml: '',
      problems: [{ kind: 'fatal', message: err.message }],
    }));
    process.exit(1);
  });
}

export { auditLayout, buildManualLaneDI, compileIRtoBpmn, normalizeGateways };
