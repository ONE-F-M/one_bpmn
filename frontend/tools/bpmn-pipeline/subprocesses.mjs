/**
 * Sub-processes step.
 *
 * A sub-process node may carry `children: { nodes, flows }`. Each scope is
 * normalised and checked on its own, and drawn either on its own plane
 * (collapsed) or inside its own box on the main plane (expanded).
 *
 * An expanded sub-process's steps are laid out first, on their own, to learn
 * how big the box must be; the main layout then treats the box as one node of
 * that size.
 */

import { buildManualLaneDI } from "./layout.mjs";
import {
  assertGatewayPairing,
  assertNoImplicitSplitOrJoin,
  normalizeGateways,
} from "./normalise.mjs";
import { EXPANDED_HEADER, EXPANDED_PAD } from "./shared.mjs";

export const subProcessesOf = (ir) =>
  (ir.nodes || []).filter((n) => n.type === "subProcess" && n.children);

// Flows may only join nodes of the scope that declares them.
export function assertSubProcessScopes(ir) {
  const problems = [];
  const descendantIds = (node) =>
    (node.children.nodes || []).flatMap((c) => [
      c.id,
      ...(c.children ? descendantIds(c) : []),
    ]);
  const check = (scope, owner) => {
    const here = new Set((scope.nodes || []).map((n) => n.id));
    const inner = new Set(subProcessesOf(scope).flatMap(descendantIds));
    for (const f of scope.flows || []) {
      for (const end of [f.from, f.to]) {
        if (here.has(end)) continue;
        if (owner || inner.has(end)) {
          problems.push({
            kind: "structure",
            rule: "subprocess-scope",
            elementId: owner || end,
            message:
              `Flow ${f.from} -> ${f.to} joins "${end}", which is not in the same ` +
              (owner ? `sub-process "${owner}"` : "scope") +
              ". Keep the flows of a sub-process between its own steps.",
          });
        }
      }
    }
    for (const sub of subProcessesOf(scope)) check(sub.children, sub.id);
  };
  check(ir, null);
  return problems;
}

// Normalise every sub-process scope; returns the IR and any structural problems.
export function normaliseSubProcesses(ir) {
  const problems = [];
  const walk = (scope) => ({
    ...scope,
    nodes: scope.nodes.map((n) => {
      if (n.type !== "subProcess" || !n.children) return n;
      const norm = normalizeGateways({
        name: n.name,
        nodes: n.children.nodes || [],
        flows: n.children.flows || [],
      });
      problems.push(
        ...assertNoImplicitSplitOrJoin(norm),
        ...assertGatewayPairing(norm),
      );
      const inner = walk({ nodes: norm.nodes, flows: norm.flows });
      return { ...n, children: { nodes: inner.nodes, flows: inner.flows } };
    }),
  });
  return { ir: walk(ir), problems };
}

// Size every expanded sub-process from the layout of its own steps.
export function sizeExpandedSubProcesses(ir, problems) {
  return {
    ...ir,
    nodes: ir.nodes.map((n) => {
      if (n.type !== "subProcess" || !n.expanded || !n.children) return n;
      const inner = sizeExpandedSubProcesses(
        { nodes: n.children.nodes || [], flows: n.children.flows || [] },
        problems,
      );
      const grid = {
        name: n.name,
        lanes: [{ id: "__lane", name: n.name || "Sub-process" }],
        nodes: inner.nodes.map((c) => ({ ...c, lane: "__lane" })),
        flows: inner.flows,
      };
      const { diSection, problems: diProblems } = buildManualLaneDI(grid, {
        pool: false,
      });
      problems.push(...(diProblems || []));
      if (!diSection) return n;
      const open =
        diSection.indexOf(">", diSection.indexOf("<bpmndi:BPMNPlane")) + 1;
      const body = diSection.slice(
        open,
        diSection.lastIndexOf("</bpmndi:BPMNPlane>"),
      );
      const xs = [],
        ys = [];
      for (const m of body.matchAll(
        /<dc:Bounds\s+x="(-?[\d.]+)"\s+y="(-?[\d.]+)"\s+width="([\d.]+)"\s+height="([\d.]+)"/g,
      )) {
        xs.push(+m[1], +m[1] + +m[3]);
        ys.push(+m[2], +m[2] + +m[4]);
      }
      for (const m of body.matchAll(
        /<di:waypoint\s+x="(-?[\d.]+)"\s+y="(-?[\d.]+)"/g,
      )) {
        xs.push(+m[1]);
        ys.push(+m[2]);
      }
      const minX = Math.min(...xs),
        minY = Math.min(...ys);
      return {
        ...n,
        children: { nodes: inner.nodes, flows: inner.flows },
        w: Math.max(200, Math.ceil(Math.max(...xs) - minX) + 2 * EXPANDED_PAD),
        h: Math.max(
          120,
          Math.ceil(Math.max(...ys) - minY) + EXPANDED_PAD + EXPANDED_HEADER,
        ),
        _inner: { minX, minY, body },
      };
    }),
  };
}

// One extra BPMNDiagram per sub-process, laid out with the same builder as the main plane.
export function buildSubProcessPlanes(ir) {
  const sections = [];
  const problems = [];
  for (const sub of subProcessesOf(ir)) {
    if (!sub.expanded) {
      const gridIR = {
        name: sub.name,
        lanes: [{ id: "__lane", name: sub.name || "Sub-process" }],
        nodes: (sub.children.nodes || []).map((n) => ({
          ...n,
          lane: "__lane",
        })),
        flows: sub.children.flows || [],
      };
      const { diSection, problems: diProblems } = buildManualLaneDI(gridIR, {
        pool: false,
      });
      problems.push(...diProblems);
      if (diSection) {
        sections.push(
          diSection
            .replace(
              'BPMNDiagram id="BPMNDiagram_1"',
              `BPMNDiagram id="BPMNDiagram_${sub.id}"`,
            )
            .replace(
              'BPMNPlane id="BPMNPlane_1" bpmnElement="Process_1"',
              `BPMNPlane id="BPMNPlane_${sub.id}" bpmnElement="${sub.id}"`,
            ),
        );
      }
    }
    const nested = buildSubProcessPlanes(sub.children);
    sections.push(...nested.sections);
    problems.push(...nested.problems);
  }
  return { sections, problems };
}
