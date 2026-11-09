/**
 * Constants and helpers shared by more than one pipeline step.
 *
 * Nothing here has side effects; every step imports what it needs.
 */

export const GATEWAY_TYPES = new Set([
  "exclusiveGateway",
  "parallelGateway",
  "inclusiveGateway",
]);

// Layout constants for manual lane DI generation. Lane heights and column
// spacing are no longer fixed: buildManualLaneDI sizes each lane band and each
// column gutter to the routing channels it actually has to carry.
export const PARTICIPANT_X = 150;
export const PARTICIPANT_Y = 80;
export const POOL_HEADER_W = 30; // vertical pool-name strip (leftmost)
export const LANE_HEADER_W = 30; // per-lane name strip

// Per-type element dimensions (pixels)
const NODE_DIMS = {
  startEvent: { w: 36, h: 36 },
  endEvent: { w: 36, h: 36 },
  intermediateThrowEvent: { w: 36, h: 36 },
  intermediateCatchEvent: { w: 36, h: 36 },
  exclusiveGateway: { w: 50, h: 50 },
  parallelGateway: { w: 50, h: 50 },
  inclusiveGateway: { w: 50, h: 50 },
};
const DEFAULT_NODE_DIMS = { w: 100, h: 80 };

// An expanded sub-process carries the size its steps need; every other node takes its type's size.
export function nodeDims(node) {
  if (node.w && node.h) return { w: node.w, h: node.h };
  return NODE_DIMS[node.type] || DEFAULT_NODE_DIMS;
}

// An expanded sub-process draws its steps inside its own box on the main plane.
// The box geometry is shared by the sub-process step (which sizes the box) and
// the layout step (which places the steps inside it).
export const EXPANDED_PAD = 24; // space between the box and the steps inside it
export const EXPANDED_HEADER = 36; // room along the top for the sub-process name

// The steps of an expanded sub-process, moved to sit inside its box.
export function innerDiagram(inner, box) {
  const dx = box.x + EXPANDED_PAD - inner.minX;
  const dy = box.y + EXPANDED_HEADER - inner.minY;
  return inner.body.replace(
    /(<(?:dc:Bounds|di:waypoint)\s+x=")(-?[\d.]+)("\s+y=")(-?[\d.]+)/g,
    (_, head, x, mid, y) =>
      head + Math.round(+x + dx) + mid + Math.round(+y + dy),
  );
}
