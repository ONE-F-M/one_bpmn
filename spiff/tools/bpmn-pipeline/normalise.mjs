/**
 * Normalise step: eliminate task/event fan-out and fan-in, then check the
 * result and the declared gateway pairs.
 *
 *   1. normalizeGateways        - insert split/join gateways
 *   2. assertNoImplicitSplitOrJoin - structural check on the normalised IR
 *   3. assertGatewayPairing     - reject mismatched opens/closes pairs
 */

import { GATEWAY_TYPES } from "./shared.mjs";

function buildAdjacency(nodes, flows) {
  const out = new Map(nodes.map((n) => [n.id, []]));
  const inn = new Map(nodes.map((n) => [n.id, []]));
  for (const f of flows) {
    (out.get(f.from) || []).push(f);
    (inn.get(f.to) || []).push(f);
  }
  return { out, inn };
}

let _seq = 0;
function uid(prefix) {
  return `${prefix}_${++_seq}`;
}

// ── Pass 1: normalizeGateways ────────────────────────────────────────────────
//
// Invariant enforced: no non-gateway node has >1 incoming or >1 outgoing flow.
//
//   no-implicit-split (task with >1 outgoing) → insert split gateway after node
//   fake-join         (task with >1 incoming) → insert join  gateway before node
//
// Inserted gateways are tagged { inferred: true } so downstream code can
// distinguish them from explicitly modelled gateways.

export function normalizeGateways(ir) {
  // Shapes sharing an id are one node (flows name nodes by id); keep the first and drop now-identical flows.
  const seenNodes = new Set();
  let nodes = ir.nodes
    .filter((n) => !seenNodes.has(n.id) && seenNodes.add(n.id))
    .map((n) => ({ ...n }));
  const seenFlows = new Set();
  let flows = ir.flows
    .filter((f) => {
      const key = JSON.stringify([
        f.from,
        f.to,
        f.condition || "",
        !!f.default,
        f.name || "",
      ]);
      return !seenFlows.has(key) && seenFlows.add(key);
    })
    .map((f) => ({ ...f }));

  // ── Fan-out pass ──
  {
    const { out } = buildAdjacency(nodes, flows);
    for (const n of [...nodes]) {
      if (GATEWAY_TYPES.has(n.type)) continue;
      const outFlows = out.get(n.id) || [];
      if (outFlows.length <= 1) continue;

      const gwType = outFlows.some((f) => f.condition)
        ? "exclusiveGateway"
        : "parallelGateway";
      const gwId = uid("gw_split");
      nodes.push({
        id: gwId,
        type: gwType,
        name: `${n.name} Split`,
        inferred: true,
      });

      // Repoint: all flows previously sourced from N now come from the new gateway
      flows = flows.map((f) =>
        outFlows.includes(f) ? { ...f, from: gwId } : f,
      );
      // Bridge: N → gateway
      flows.push({ from: n.id, to: gwId });

      // Exclusive split must have exactly one default flow.
      // If all outgoing flows carry conditions (no obvious fallback), strip the last
      // one's condition and promote it to the unconditional default path.
      if (gwType === "exclusiveGateway") {
        if (!flows.filter((f) => f.from === gwId).some((f) => f.default)) {
          let di = flows.findIndex(
            (f) => f.from === gwId && !f.condition && !f.default,
          );
          const mustStrip = di < 0;
          if (di < 0)
            di = flows.reduce((best, f, i) => (f.from === gwId ? i : best), -1);
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

      const gwId = uid("gw_join");
      nodes.push({
        id: gwId,
        type: "exclusiveGateway",
        name: `${n.name} Join`,
        inferred: true,
      });

      // Repoint: all flows previously targeting N now target the join gateway
      flows = flows.map((f) => (inFlows.includes(f) ? { ...f, to: gwId } : f));
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
      const inFlows = inn.get(n.id) || [];
      const outFlows = out.get(n.id) || [];
      if (inFlows.length <= 1 || outFlows.length <= 1) continue;

      // If none of the outgoing flows carry conditions or a default, the original gateway
      // had no routing logic - make the fork parallel so all paths run concurrently and
      // no conditional-flows check fires on the inferred fork.
      const forkType = outFlows.some((f) => f.condition || f.default)
        ? n.type
        : "parallelGateway";
      const forkId = uid("gw_fork");
      nodes.push({
        id: forkId,
        type: forkType,
        name: `${n.name} Fork`,
        inferred: true,
      });

      // All outgoing flows from original now come from the fork gateway
      flows = flows.map((f) =>
        outFlows.includes(f) ? { ...f, from: forkId } : f,
      );
      // Bridge: join → fork
      flows.push({ from: n.id, to: forkId });

      // Exclusive fork must have exactly one default flow (same robust logic as fan-out pass).
      if (forkType === "exclusiveGateway") {
        if (!flows.filter((f) => f.from === forkId).some((f) => f.default)) {
          let di = flows.findIndex(
            (f) => f.from === forkId && !f.condition && !f.default,
          );
          const mustStrip = di < 0;
          if (di < 0)
            di = flows.reduce(
              (best, f, i) => (f.from === forkId ? i : best),
              -1,
            );
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

  // ── Cleanup pass: remove superfluous gateways (1 in + 1 out) ──
  // normalizeGateways may insert join/fork gateways that end up unnecessary
  // when the IR structure doesn't actually require them (e.g. a join gateway
  // inserted for a node that only has one actual predecessor after other
  // normalization). Remove them and bridge predecessor → successor directly.
  {
    let changed = true;
    while (changed) {
      changed = false;
      const { out, inn } = buildAdjacency(nodes, flows);
      for (const n of [...nodes]) {
        if (!GATEWAY_TYPES.has(n.type)) continue;
        const inFlows = inn.get(n.id) || [];
        const outFlows = out.get(n.id) || [];
        if (inFlows.length !== 1 || outFlows.length !== 1) continue;

        // This gateway is superfluous: exactly 1 in, 1 out
        const predFlow = inFlows[0]; // { from, to, ... }
        const succFlow = outFlows[0]; // { from, to, ... }

        // Bridge: predecessor → successor (preserve name/condition from the outgoing flow)
        const bridgeFlow = {
          from: predFlow.from,
          to: succFlow.to,
          name: succFlow.name || predFlow.name || "",
        };
        if (succFlow.condition) bridgeFlow.condition = succFlow.condition;
        if (succFlow.default) bridgeFlow.default = succFlow.default;

        // Remove the two old flows and the gateway node
        flows = flows.filter((f) => f !== predFlow && f !== succFlow);
        flows.push(bridgeFlow);
        nodes = nodes.filter((nd) => nd.id !== n.id);
        changed = true;
        break; // restart scan since adjacency changed
      }
    }
  }

  return { ...ir, nodes, flows };
}

// ── Post-normalization structural check ──────────────────────────────────────
//
// After all three normalizeGateways passes, every non-gateway node must have
// at most 1 outgoing and at most 1 incoming flow.  If any remain it means
// normalizeGateways has an unhandled edge case - surface it immediately so the
// Python repair loop can handle it rather than silently producing bad XML.

export function assertNoImplicitSplitOrJoin(ir) {
  const problems = [];
  const { out, inn } = buildAdjacency(ir.nodes, ir.flows);
  for (const n of ir.nodes) {
    if (GATEWAY_TYPES.has(n.type)) continue;
    const outCount = (out.get(n.id) || []).length;
    const inCount = (inn.get(n.id) || []).length;
    if (outCount > 1) {
      problems.push({
        kind: "lint",
        rule: "no-implicit-split",
        elementId: n.id,
        message: `Node "${n.id}" (${n.type}) still has ${outCount} outgoing flows after normalisation \u2014 normalizeGateways bug.`,
      });
    }
    if (inCount > 1) {
      problems.push({
        kind: "lint",
        rule: "fake-join",
        elementId: n.id,
        message: `Node "${n.id}" (${n.type}) still has ${inCount} incoming flows after normalisation \u2014 normalizeGateways bug.`,
      });
    }
  }
  return problems;
}

// ── Pass 2: assertGatewayPairing ─────────────────────────────────────────────
//
// A node with `closes: "<splitId>"` declares it is the join counterpart of that
// split. The types must match: a parallelGateway split must be closed by a
// parallelGateway join. Mismatch passes bpmnlint but deadlocks Spiff at runtime.
// This pass rejects before compiling so the error reaches the LLM repair loop.

export function assertGatewayPairing(ir) {
  const problems = [];
  const nodeMap = new Map(ir.nodes.map((n) => [n.id, n]));

  for (const n of ir.nodes) {
    if (!n.closes) continue;
    const split = nodeMap.get(n.closes);
    if (!split) {
      problems.push({
        kind: "pairing",
        message: `Node "${n.id}" (${n.name}) declares closes="${n.closes}" but that node does not exist.`,
      });
    } else if (split.type !== n.type) {
      problems.push({
        kind: "pairing",
        message:
          `Gateway pairing mismatch: "${n.id}" (type=${n.type}) closes "${split.id}" (type=${split.type}). ` +
          `A ${split.type} split must be closed by a ${split.type} join, not a ${n.type}.`,
      });
    }
  }

  return problems;
}
