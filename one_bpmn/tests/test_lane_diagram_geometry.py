# Copyright (c) 2026, one-fm and contributors
"""Geometry of a generated swim-lane diagram.

A generated map is read by a process owner, so "correct but unreadable" has not
done its job. These tests measure the drawing rather than eyeballing it, because
eyeballing is exactly what let a 916-overlap diagram ship once already.

Three of the four properties here are INVARIANTS and are asserted absolutely:

  * every segment is orthogonal — no diagonals
  * no segment passes through a shape it does not connect to
  * no two segments of the same edge double back on each other

The fourth — how many pairs of segments overlap or cross — is a BUDGET, not an
invariant. A process graph with back-edges and many-to-one joins is generally
non-planar, so some crossings are forced by the graph and no drawing can remove
them. The budget is there to stop regressions, and the numbers in it are the
measured output of the current router. Improving the router should mean lowering
them; nothing should ever raise them without a reason in the commit message.
"""

import itertools
import xml.etree.ElementTree as ET

from frappe.tests.utils import FrappeTestCase

from one_bpmn.agents.bpmn_ir_pipeline import compile_ir

DI = "http://www.omg.org/spec/BPMN/20100524/DI"
DC = "http://www.omg.org/spec/DD/20100524/DC"
DIW = "http://www.omg.org/spec/DD/20100524/DI"
BPMN = "http://www.omg.org/spec/BPMN/20100524/MODEL"

TOUCH = 6.0        # segments this close to an endpoint are meeting, not crossing
COLLINEAR = 10.0   # parallel segments this close read as one line


def _fan_and_loop_ir():
	"""A shape that has broken the router before.

	A gateway fanning three ways (three flows leaving one 50px diamond), a
	join taking three flows back in, a lane change, and a back edge — the four
	things that produced collinear stubs and strip crossings on the real maps.
	"""
	return {
		"name": "Geometry Fixture",
		"lanes": [{"id": "officer", "name": "Officer"}, {"id": "system", "name": "System"}],
		"nodes": [
			{"id": "start", "type": "startEvent", "name": "Request raised", "lane": "officer"},
			{"id": "triage", "type": "userTask", "name": "Triage", "lane": "officer"},
			{"id": "split", "type": "exclusiveGateway", "name": "Which route?", "lane": "officer"},
			{"id": "fast", "type": "userTask", "name": "Fast path", "lane": "officer"},
			{"id": "slow", "type": "userTask", "name": "Slow path", "lane": "officer"},
			{"id": "audit", "type": "scriptTask", "name": "Audit", "lane": "system"},
			{"id": "notify", "type": "serviceTask", "name": "Notify", "lane": "system"},
			{"id": "review", "type": "userTask", "name": "Review", "lane": "officer"},
			{"id": "done", "type": "endEvent", "name": "Closed", "lane": "officer"},
		],
		"flows": [
			{"from": "start", "to": "triage"},
			{"from": "triage", "to": "split"},
			{"from": "split", "to": "fast", "name": "Fast"},
			{"from": "split", "to": "slow", "name": "Slow"},
			{"from": "split", "to": "audit", "name": "Audit only"},
			{"from": "fast", "to": "review"},
			{"from": "slow", "to": "review"},
			{"from": "audit", "to": "notify"},
			{"from": "notify", "to": "review"},
			{"from": "review", "to": "done"},
			{"from": "review", "to": "triage", "name": "Rework"},
		],
	}


def _return_loop_ir():
	"""A rework loop running back past a branch that leaves for the lane below.

	Two things collide here and neither is exotic: a gateway with one branch
	carrying on in its own lane and another dropping to the lane beneath, and a
	loop returning across the width of the lane to re-enter earlier. Routed
	naively all three flows fight over the band under the lane's nodes, so the
	loop and the drop cross at right angles — and the branch that carried
	straight on is crossed too, because the drop has to stub out past it first.

	The drawing has an answer for all three: leave through the face you are
	heading for, and put the loop on the side of the lane the traffic is not
	using. This fixture holds that answer in place.
	"""
	return {
		"name": "Nightly Data Import",
		"lanes": [
			{"id": "importer", "name": "Data Importer"},
			{"id": "migrator", "name": "Data Migrator"},
		],
		"nodes": [
			{"id": "start", "type": "startEvent", "name": "Nightly schedule fires", "lane": "importer"},
			{"id": "fetch", "type": "serviceTask", "name": "Fetch source extract", "lane": "importer"},
			{"id": "validate", "type": "scriptTask", "name": "Validate records", "lane": "importer"},
			{"id": "valid", "type": "exclusiveGateway", "name": "Valid?", "lane": "importer"},
			{"id": "transform", "type": "scriptTask", "name": "Transform records", "lane": "migrator"},
			{"id": "quarantine", "type": "serviceTask", "name": "Quarantine rejects", "lane": "importer"},
			{"id": "reprocess", "type": "userTask", "name": "Review and reprocess", "lane": "importer"},
			{"id": "load", "type": "serviceTask", "name": "Load into warehouse", "lane": "migrator"},
			{"id": "done", "type": "endEvent", "name": "Import complete", "lane": "migrator"},
		],
		"flows": [
			{"from": "start", "to": "fetch"},
			{"from": "fetch", "to": "validate"},
			{"from": "validate", "to": "valid"},
			{"from": "valid", "to": "transform", "name": "Valid"},
			{"from": "valid", "to": "quarantine", "name": "Invalid"},
			{"from": "transform", "to": "load", "name": "Transformed"},
			{"from": "quarantine", "to": "reprocess"},
			{"from": "reprocess", "to": "validate", "name": "Reprocess"},
			{"from": "load", "to": "done"},
		],
	}


def _orient(seg):
	(x1, y1), (x2, y2) = seg
	if abs(y1 - y2) < 0.5:
		return "h"
	if abs(x1 - x2) < 0.5:
		return "v"
	return "diagonal"


def _measure(xml_text):
	root = ET.fromstring(xml_text.encode("utf-8"))
	plane = root.find(f".//{{{DI}}}BPMNPlane")

	# Lanes and the pool are containers; an edge inside one is not "through" it.
	containers = {
		el.get("id")
		for el in root.iter()
		if el.tag.endswith(("lane", "participant", "laneSet"))
	}
	shapes = {}
	for sh in plane.findall(f"{{{DI}}}BPMNShape"):
		bounds = sh.find(f"{{{DC}}}Bounds")
		if bounds is None or sh.get("bpmnElement") in containers:
			continue
		shapes[sh.get("bpmnElement")] = tuple(
			float(bounds.get(k)) for k in ("x", "y", "width", "height")
		)

	edges = {}
	for edge in plane.findall(f"{{{DI}}}BPMNEdge"):
		pts = [
			(float(w.get("x")), float(w.get("y")))
			for w in edge.findall(f"{{{DIW}}}waypoint")
		]
		if len(pts) >= 2:
			edges[edge.get("bpmnElement")] = pts

	segs = [
		(eid, (pts[i], pts[i + 1]))
		for eid, pts in edges.items()
		for i in range(len(pts) - 1)
	]

	diagonals = [eid for eid, s in segs if _orient(s) == "diagonal"]

	crossings, overlaps = 0, 0
	for (e1, s1), (e2, s2) in itertools.combinations(segs, 2):
		if e1 == e2:
			continue
		o1, o2 = _orient(s1), _orient(s2)
		if {o1, o2} == {"h", "v"}:
			h, v = (s1, s2) if o1 == "h" else (s2, s1)
			(hx1, hy), (hx2, _) = h
			(vx, vy1), (_, vy2) = v
			if (min(hx1, hx2) + TOUCH < vx < max(hx1, hx2) - TOUCH
					and min(vy1, vy2) + TOUCH < hy < max(vy1, vy2) - TOUCH):
				crossings += 1
		elif o1 == o2 and o1 != "diagonal":
			if o1 == "h":
				if abs(s1[0][1] - s2[0][1]) > COLLINEAR:
					continue
				a, b = sorted([s1[0][0], s1[1][0]]), sorted([s2[0][0], s2[1][0]])
			else:
				if abs(s1[0][0] - s2[0][0]) > COLLINEAR:
					continue
				a, b = sorted([s1[0][1], s1[1][1]]), sorted([s2[0][1], s2[1][1]])
			if min(a[1], b[1]) - max(a[0], b[0]) > TOUCH * 2:
				overlaps += 1

	through = set()
	for eid, seg in segs:
		for sid, (x, y, w, h) in shapes.items():
			(ax, ay), (bx, by) = seg
			if _orient(seg) == "h" and y + TOUCH < ay < y + h - TOUCH:
				if min(ax, bx) + TOUCH < x + w / 2 < max(ax, bx) - TOUCH:
					through.add((eid, sid))
			elif _orient(seg) == "v" and x + TOUCH < ax < x + w - TOUCH:
				if min(ay, by) + TOUCH < y + h / 2 < max(ay, by) - TOUCH:
					through.add((eid, sid))

	bends = 0
	for pts in edges.values():
		for i in range(1, len(pts) - 1):
			if _orient((pts[i - 1], pts[i])) != _orient((pts[i], pts[i + 1])):
				bends += 1

	return {
		"edges": len(edges),
		"diagonals": diagonals,
		"crossings": crossings,
		"overlaps": overlaps,
		"through": sorted(through),
		"bends": bends,
	}


class TestLaneDiagramGeometry(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		result = compile_ir(_fan_and_loop_ir())
		cls.result = result
		cls.xml = result.get("xml") or ""
		loop = compile_ir(_return_loop_ir())
		cls.loop_result = loop
		cls.loop_xml = loop.get("xml") or ""

	def test_the_fixture_compiles(self):
		self.assertTrue(self.result.get("ok"), self.result.get("problems"))
		self.assertIn("BPMNPlane", self.xml, "no diagram was generated")

	def test_every_segment_is_orthogonal(self):
		"""A diagonal in a BPMN diagram is always a layout bug, never a choice."""
		m = _measure(self.xml)
		self.assertEqual(m["diagonals"], [], "diagonal segments in a generated diagram")

	def test_no_segment_passes_through_an_unrelated_shape(self):
		"""The invariant the reserved-corridor model exists to guarantee.

		This is the one that made diagrams genuinely unreadable rather than
		merely untidy — a line straight through the middle of a task it has
		nothing to do with.
		"""
		m = _measure(self.xml)
		self.assertEqual(m["through"], [], "edge segments crossing unrelated shapes")

	def test_no_edge_doubles_back_on_itself(self):
		"""Two consecutive segments of one edge must not retrace each other."""
		root = ET.fromstring(self.xml.encode("utf-8"))
		plane = root.find(f".//{{{DI}}}BPMNPlane")
		for edge in plane.findall(f"{{{DI}}}BPMNEdge"):
			pts = [
				(float(w.get("x")), float(w.get("y")))
				for w in edge.findall(f"{{{DIW}}}waypoint")
			]
			for i in range(len(pts) - 1):
				self.assertNotEqual(
					pts[i], pts[i + 1],
					f"{edge.get('bpmnElement')} has a zero-length segment",
				)

	def test_crossing_and_overlap_budget(self):
		"""A regression guard, not a proof of correctness.

		The fixture's graph is small enough that the router should draw it
		cleanly; if these ever need raising, the router got worse. If a change
		lowers them, lower the budget in the same commit so the gain is kept.
		"""
		m = _measure(self.xml)
		# Measured on this fixture with the current router. Overlaps are the one
		# to keep pressing on: two lines drawn on top of each other read worse
		# than two that cross, so the budget for them is deliberately tight.
		# The crossings that remain are dominated by a gutter vertical meeting a
		# strip horizontal, which is inherent to routing one strip per lane —
		# lowering that number means reworking the strip model, not tuning this.
		self.assertLessEqual(m["overlaps"], 0, f"overlapping segment pairs rose: {m}")
		self.assertLessEqual(m["crossings"], 1, f"crossing segment pairs rose: {m}")
		self.assertLessEqual(
			m["bends"] / max(m["edges"], 1), 0.75,
			f"average bends per edge rose: {m}",
		)

	def test_the_return_loop_diagram_is_clean(self):
		"""The shape a reader actually complains about, held at zero.

		A loop returning across a lane and a branch dropping out of it are the
		two commonest things in a real process map, and together they used to
		produce three crossings on nine nodes. Nothing forces them: this graph
		is planar as drawn, so the budget is zero rather than a measured
		number, and any crossing at all is a routing failure.
		"""
		self.assertTrue(self.loop_result.get("ok"), self.loop_result.get("problems"))
		m = _measure(self.loop_xml)
		self.assertEqual(m["diagonals"], [], f"diagonal segments: {m}")
		self.assertEqual(m["through"], [], f"edges crossing unrelated shapes: {m}")
		self.assertEqual(m["overlaps"], 0, f"overlapping segment pairs: {m}")
		self.assertEqual(m["crossings"], 0, f"crossing segment pairs: {m}")
