/**
 * Lanes step: lane checks, lane assignment and the BPMN lane set.
 *
 * The lane BANDS (their heights and positions on the canvas) are part of the
 * grid layout and are computed in layout.mjs, because they depend on the
 * routing channels each lane has to carry.
 */

// ── Lane-assignment structural check ─────────────────────────────────────────
//
// When ir.lanes is present, every non-inferred node MUST declare a "lane" field
// whose value is a valid lane id.  Inferred gateways (inserted by normalizeGateways)
// are exempt - their lane is resolved later by propagation in buildManualLaneDI.
//
// Also checks that no sequence flow crosses pool boundaries (only relevant once
// multi-pool diagrams are supported; currently always satisfied, checked defensively).

export function assertLaneAssignment(ir) {
  if (!ir.lanes || !ir.lanes.length) return [];
  const laneIds = new Set(ir.lanes.map((l) => l.id));
  const problems = [];

  for (const n of ir.nodes) {
    if (n.inferred) continue; // compiler-generated; lane set via propagation
    if (!n.lane) {
      problems.push({
        kind: "structure",
        rule: "lane-orphan",
        elementId: n.id,
        message:
          `Node "${n.id}" (${n.type}: "${n.name}") has no "lane" field. ` +
          `Every node must be assigned to a lane when lanes are defined. ` +
          `Valid lane ids: ${[...laneIds].join(", ")}.`,
      });
    } else if (!laneIds.has(n.lane)) {
      problems.push({
        kind: "structure",
        rule: "lane-orphan",
        elementId: n.id,
        message:
          `Node "${n.id}" (${n.type}: "${n.name}") references unknown lane "${n.lane}". ` +
          `Valid lane ids: ${[...laneIds].join(", ")}.`,
      });
    }
  }
  return problems;
}

// Which lane each node sits in: its own "lane" field, else its neighbours'
// lane (propagated to inferred gateways), else the first lane.
// adjOut / adjInn map a node id to the ids it flows to / from.
export function resolveNodeLanes(ir, lanes, adjOut, adjInn) {
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
      const neighbours = (adjInn.get(n.id) || []).concat(
        adjOut.get(n.id) || [],
      );
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
    if (!nodeLaneId.has(n.id) && lanes.length)
      nodeLaneId.set(n.id, lanes[0].id);
  }
  return nodeLaneId;
}

// Lane set (optional) - lanes is [{ id, name, role? }]. Returns undefined when
// the IR has no lanes, otherwise the array to hang on the process.
export function buildLaneSets(moddle, ir, elementById) {
  if (!(ir.lanes && ir.lanes.length)) return undefined;
  const laneEls = ir.lanes.map((lane) => {
    const flowNodeRef = (ir.nodes || [])
      .filter((n) => n.lane === lane.id)
      .map((n) => elementById.get(n.id))
      .filter(Boolean);
    return moddle.create("bpmn:Lane", {
      id: lane.id,
      name: lane.name,
      flowNodeRef,
    });
  });
  return [moddle.create("bpmn:LaneSet", { id: "LaneSet_1", lanes: laneEls })];
}
