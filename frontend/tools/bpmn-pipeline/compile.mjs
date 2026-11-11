/**
 * Compile step: build the bpmn-moddle tree (no layout) and serialise it, then
 * inject the BPMNDI section the layout step produced.
 */

import { BpmnModdle } from "bpmn-moddle";
import { buildLaneSets } from "./lanes.mjs";

const SPIFF_NS = "http://spiffworkflow.org/bpmn/schema/1.0/core";

const BPMN_TYPE_MAP = {
  startEvent: "bpmn:StartEvent",
  endEvent: "bpmn:EndEvent",
  intermediateThrowEvent: "bpmn:IntermediateThrowEvent",
  intermediateCatchEvent: "bpmn:IntermediateCatchEvent",
  task: "bpmn:ScriptTask", // fallback; normalised IR should never emit bare task
  userTask: "bpmn:UserTask",
  scriptTask: "bpmn:ScriptTask",
  serviceTask: "bpmn:ServiceTask",
  manualTask: "bpmn:ManualTask",
  businessRuleTask: "bpmn:BusinessRuleTask",
  exclusiveGateway: "bpmn:ExclusiveGateway",
  parallelGateway: "bpmn:ParallelGateway",
  inclusiveGateway: "bpmn:InclusiveGateway",
  subProcess: "bpmn:SubProcess",
  callActivity: "bpmn:CallActivity",
};

// ── Pass 3: compileIRtoBpmn ──────────────────────────────────────────────────
//
// Deterministic: same IR always produces the same moddle tree.
// Stable IDs are used as-is from the IR; flow IDs are derived from source+target+index.
// Incoming/outgoing refs and default pointers are wired exactly once.

export async function compileIRtoBpmn(ir) {
  const moddle = new BpmnModdle();
  const flowElements = [];
  const elementById = new Map();

  // Set when any node carries configuration, so the namespace is declared only
  // on diagrams that actually use it.
  let usesSpiffNS = false;

  // 1-3. Semantic nodes, sequence flows and default flows, one scope at a time.
  // A sub-process node carries its own steps as `children`; they are built into
  // the sub-process element, so they never join the main process.
  // The editor lints on each step's incoming/outgoing references. The canvas adds them to the
  // main process, but never inside a sub-process, so the steps of a sub-process get them here.
  const buildScope = (nodes, flows, nested = false) => {
    const scopeEls = [];
    const scopeById = new Map();
    // Do NOT pass incoming/outgoing arrays - bpmn-moddle auto-wires them through the
    // sourceRef/targetRef inverse associations when it processes the flowElements.
    // Passing them AND manually pushing causes each flow to appear twice in the output.
    for (const n of nodes) {
      const isNoneTask = n.type === "task" && ir.executable === false;
      const bpmnType = isNoneTask
        ? "bpmn:Task"
        : BPMN_TYPE_MAP[n.type] || "bpmn:ScriptTask";
      const el = moddle.create(bpmnType, { id: n.id, name: n.name });
      if (n.type === "callActivity" && n.calledElement)
        el.calledElement = n.calledElement;
      // Task configuration, already resolved to final attribute names by
      // bpmn_task_config.py. Written through $attrs because the spiffworkflow
      // descriptor declares none of them - the same way the editor stores them.
      for (const [key, value] of Object.entries(n.attrs || {})) {
        if (value !== undefined && value !== null && value !== "") {
          el.$attrs[`spiffworkflow:${key}`] = String(value);
          usesSpiffNS = true;
        }
      }
      if (n.type === "subProcess" && n.children) {
        el.flowElements = buildScope(
          n.children.nodes || [],
          n.children.flows || [],
          true,
        );
      }
      scopeById.set(n.id, el);
      elementById.set(n.id, el);
      scopeEls.push(el);
    }

    // Setting sourceRef/targetRef is sufficient; moddle wires the inverse
    // incoming/outgoing references automatically via its type descriptors.
    for (let i = 0; i < flows.length; i++) {
      const f = flows[i];
      const src = scopeById.get(f.from);
      const tgt = scopeById.get(f.to);
      if (!src || !tgt) continue;

      const sf = moddle.create("bpmn:SequenceFlow", {
        id: f.id || `flow_${f.from}_${f.to}_${i}`,
        name: f.name || "",
        sourceRef: src,
        targetRef: tgt,
      });

      if (f.condition) {
        sf.conditionExpression = moddle.create("bpmn:FormalExpression", {
          body: f.condition,
        });
      }
      if (f.default) src.default = sf;
      if (nested) {
        src.outgoing = [...(src.outgoing || []), sf];
        tgt.incoming = [...(tgt.incoming || []), sf];
      }
      scopeEls.push(sf);
    }
    return scopeEls;
  };
  flowElements.push(...buildScope(ir.nodes, ir.flows));

  // 4. Lane set (optional)
  const laneSets = buildLaneSets(moddle, ir, elementById);

  // 5. Process
  const processEl = moddle.create("bpmn:Process", {
    id: "Process_1",
    isExecutable: ir.executable !== false,
    flowElements,
    ...(laneSets ? { laneSets } : {}),
  });

  // 6. Collaboration + Participant (required for bpmn-js to render swim lanes)
  const rootElements = [processEl];
  if (laneSets) {
    const participantEl = moddle.create("bpmn:Participant", {
      id: "Participant_1",
      name: ir.name || "Process",
      processRef: processEl,
    });
    const collaborationEl = moddle.create("bpmn:Collaboration", {
      id: "Collaboration_1",
      participants: [participantEl],
    });
    rootElements.unshift(collaborationEl); // collaboration must come first
  }

  const definitions = moddle.create("bpmn:Definitions", {
    id: "Definitions_1",
    targetNamespace: "http://bpmn.io/schema/bpmn",
    exporter: "processa-pipeline",
    exporterVersion: "1.0",
    rootElements,
  });

  if (usesSpiffNS) {
    definitions.$attrs["xmlns:spiffworkflow"] = SPIFF_NS;
  }

  const { xml } = await moddle.toXML(definitions, { format: true });
  return xml;
}

// Inject BPMNDI section + required namespace declarations into moddle-generated XML.
// moddle omits bpmndi/dc/di namespaces when no DI elements exist in the model tree.
export function injectLaneDI(xml, diSection) {
  let result = xml;
  if (result.indexOf("xmlns:bpmndi=") === -1) {
    result = result.replace(
      /(<bpmn:definitions)(\s)/,
      "$1" +
        ' xmlns:bpmndi="http://www.omg.org/spec/BPMN/20100524/DI"' +
        ' xmlns:dc="http://www.omg.org/spec/DD/20100524/DC"' +
        ' xmlns:di="http://www.omg.org/spec/DD/20100524/DI"' +
        "$2",
    );
  }
  return result.replace(
    "</bpmn:definitions>",
    diSection + "\n</bpmn:definitions>",
  );
}
