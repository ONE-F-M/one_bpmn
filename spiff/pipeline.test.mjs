// node --test spiff/pipeline.test.mjs
//
// The geometry is tested directly; the pipeline is driven the way Python drives
// it — IR on stdin, JSON on stdout — so the test sees exactly what compile_ir sees.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

import { properCross, collinearOverlap, segHitsBox, auditGeometry } from './src/linting/geometry.js';

const here = path.dirname(fileURLToPath(import.meta.url));
const run = (ir) => JSON.parse(spawnSync(process.execPath, [path.join(here, 'pipeline.mjs')],
  { input: JSON.stringify(ir), encoding: 'utf8' }).stdout);

test('an X is a crossing, a touch at an endpoint is not', () => {
  assert.equal(properCross([[0, 0], [10, 10]], [[0, 10], [10, 0]]), true);
  assert.equal(properCross([[0, 0], [10, 0]], [[10, 0], [10, 10]]), false);
  assert.equal(properCross([[0, 0], [10, 0]], [[0, 5], [10, 5]]), false);
});

test('lines on the same row that share a stretch overlap', () => {
  assert.equal(collinearOverlap([[0, 5], [10, 5]], [[5, 5], [20, 5]]), true);
  assert.equal(collinearOverlap([[0, 5], [10, 5]], [[10, 5], [20, 5]]), false);
  assert.equal(collinearOverlap([[0, 5], [10, 5]], [[0, 6], [10, 6]]), false);
});

test('a segment through a box is caught, one along its edge is not', () => {
  const box = { x: 10, y: 10, w: 20, h: 20 };
  assert.equal(segHitsBox([[0, 20], [40, 20]], box), true);
  assert.equal(segHitsBox([[0, 10], [40, 10]], box), false);
  assert.equal(segHitsBox([[20, 0], [20, 40]], box), true);
});

test('edges that share a node may fan out from it without a crossing', () => {
  const shapes = [{ id: 'g', x: 0, y: 0, w: 50, h: 50, container: false }];
  const edges = [
    { id: 'a', pts: [[50, 25], [100, 25], [100, 0]], src: 'g', tgt: 'x' },
    { id: 'b', pts: [[50, 25], [100, 25], [100, 60]], src: 'g', tgt: 'y' },
  ];
  const r = auditGeometry({ shapes, edges });
  assert.equal(r.crossings, 0);
});

const lanes = [{ id: 'a', name: 'A' }, { id: 'b', name: 'B' }];
const node = (id, type = 'userTask', lane = 'a') => ({ id, type, name: id, lane });

test('a planar process is drawn with zero crossings and lines through nothing', () => {
  const ir = {
    name: 'Planar', lanes,
    nodes: [node('s', 'startEvent'), node('t1'), node('g', 'exclusiveGateway'), node('t2'), node('t3', 'userTask', 'b'),
      node('j', 'exclusiveGateway'), node('t4'), node('e', 'endEvent')],
    flows: [{ from: 's', to: 't1' }, { from: 't1', to: 'g' }, { from: 'g', to: 't2', name: 'Yes', condition: 'ok' },
      { from: 'g', to: 't3', name: 'No', default: true }, { from: 't2', to: 'j' }, { from: 't3', to: 'j' },
      { from: 'j', to: 't4' }, { from: 't4', to: 'e' }],
  };
  const r = run(ir);
  assert.equal(r.ok, true, JSON.stringify(r.problems));
  assert.equal(r.layout.crossings, 0, JSON.stringify(r.layout));
  assert.equal(r.layout.throughShape, 0, JSON.stringify(r.layout));
  assert.equal(r.layout.labelCollisions, 0, JSON.stringify(r.layout));
});

test('every named event and gateway gets an explicit label box', () => {
  const ir = {
    name: 'Labels', lanes,
    nodes: [{ id: 'created', type: 'startEvent', name: 'Work Item Created', lane: 'a' },
      { id: 'orch', type: 'exclusiveGateway', name: 'Orchestrator?', lane: 'a' },
      { id: 'go', type: 'userTask', name: 'Go', lane: 'a' }, { id: 'skip', type: 'userTask', name: 'Skip', lane: 'a' },
      { id: 'join', type: 'exclusiveGateway', name: 'Merge', lane: 'a' }, { id: 'done', type: 'endEvent', name: 'Done', lane: 'a' }],
    flows: [{ from: 'created', to: 'orch' }, { from: 'orch', to: 'go', name: 'yes', condition: 'orchestrator' },
      { from: 'orch', to: 'skip', name: 'no', default: true }, { from: 'go', to: 'join' }, { from: 'skip', to: 'join' },
      { from: 'join', to: 'done' }],
  };
  const r = run(ir);
  assert.equal(r.ok, true, JSON.stringify(r.problems));
  const shapeLabels = (r.xml.match(/<bpmndi:BPMNShape[^>]*>(?:(?!<\/bpmndi:BPMNShape>)[\s\S])*?<bpmndi:BPMNLabel>/g) || []).length;
  const edgeLabels = (r.xml.match(/<bpmndi:BPMNEdge[^>]*>(?:(?!<\/bpmndi:BPMNEdge>)[\s\S])*?<bpmndi:BPMNLabel>/g) || []).length;
  assert.equal(shapeLabels, 4, 'start, fork, merge and end each carry a label box');
  assert.equal(edgeLabels, 2, 'both named branches carry a label box');
  assert.equal(r.layout.labelCollisions, 0, JSON.stringify(r.layout));
});

test('a lane-less IR is laid out without a pool and without bpmn-auto-layout', () => {
  const ir = {
    name: 'Flat',
    nodes: [{ id: 's', type: 'startEvent', name: 's' }, { id: 't', type: 'userTask', name: 't' }, { id: 'e', type: 'endEvent', name: 'e' }],
    flows: [{ from: 's', to: 't' }, { from: 't', to: 'e' }],
  };
  const r = run(ir);
  assert.equal(r.ok, true, JSON.stringify(r.problems));
  assert.match(r.xml, /<bpmndi:BPMNShape/);
  assert.doesNotMatch(r.xml, /Participant/);
  assert.equal(r.layout.crossings, 0);
});

test('a fork inside ONE lane is drawn as a diamond, not a snake', () => {
  const ir = {
    name: 'Diamond', lanes,
    nodes: [node('s', 'startEvent'), node('t1'), node('g', 'exclusiveGateway'), node('t2'), node('t3'),
      node('j', 'exclusiveGateway'), node('t4'), node('e', 'endEvent')],
    flows: [{ from: 's', to: 't1' }, { from: 't1', to: 'g' }, { from: 'g', to: 't2', name: 'Yes', condition: 'ok' },
      { from: 'g', to: 't3', name: 'No', default: true }, { from: 't2', to: 'j' }, { from: 't3', to: 'j' },
      { from: 'j', to: 't4' }, { from: 't4', to: 'e' }],
  };
  const r = run(ir);
  assert.equal(r.ok, true, JSON.stringify(r.problems));
  assert.equal(r.layout.crossings, 0, JSON.stringify(r.layout));
  assert.equal(r.layout.labelCollisions, 0, JSON.stringify(r.layout));
  // t2 and t3 share a column: same x, different y
  const at = (id) => { const m = new RegExp('bpmnElement="' + id + '">\\s*<dc:Bounds x="(\\d+)" y="(\\d+)"').exec(r.xml); return [+m[1], +m[2]]; };
  assert.equal(at('t2')[0], at('t3')[0]);
  assert.notEqual(at('t2')[1], at('t3')[1]);
});

test('unrelated nodes still take their own column (no pile-up in one cell)', () => {
  // a chain of six tasks in one lane must stay six columns wide
  const nodes = [node('s', 'startEvent')].concat(['a', 'b', 'c', 'd', 'e1', 'f'].map(n => node(n))).concat([node('end', 'endEvent')]);
  const ids = nodes.map(n => n.id);
  const flows = ids.slice(1).map((to, k) => ({ from: ids[k], to }));
  const r = run({ name: 'Chain', lanes, nodes, flows });
  assert.equal(r.ok, true);
  const xs = [...r.xml.matchAll(/bpmnElement="(?:a|b|c|d|e1|f)">\s*<dc:Bounds x="(\d+)"/g)].map(m => +m[1]);
  assert.equal(new Set(xs).size, 6, 'six distinct columns');
});
