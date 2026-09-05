"""The compiler tells the truth about crossings.

A planar flow graph must come back with a crossing-free drawing; a non-planar
one must be reported as such rather than retried, and its drawing may carry
exactly the one crossing the graph forces.
"""
import unittest

from one_bpmn.agents.bpmn_ir_pipeline import (
	_IR_IGNORABLE_RULES,
	_RULE_HINTS,
	check_topology,
	compile_ir,
	flow_pairs_from_xml,
	translate_problems,
)

LANES = [{"id": "a", "name": "A"}, {"id": "b", "name": "B"}]


def _node(nid, ntype="userTask", lane="a"):
	return {"id": nid, "type": ntype, "name": nid.replace("_", " ").title(), "lane": lane}


def _flow(a, b, **extra):
	return {"from": a, "to": b, **extra}


def planar_ir():
	"""start -> t1 -> gw -> (t2 | t3) -> join -> end, with one rework loop."""
	nodes = [
		_node("start", "startEvent"), _node("t1"), _node("gw", "exclusiveGateway"),
		_node("t2"), _node("t3", lane="b"), _node("join", "exclusiveGateway"),
		_node("t4"), _node("end", "endEvent"),
	]
	flows = [
		_flow("start", "t1"), _flow("t1", "gw"),
		_flow("gw", "t2", name="Yes", condition="ok"), _flow("gw", "t3", name="No", default=True),
		_flow("t2", "join"), _flow("t3", "join"), _flow("join", "t4"), _flow("t4", "end"),
	]
	return {"name": "Planar", "lanes": LANES, "nodes": nodes, "flows": flows}


def k33_flows():
	"""K3,3 — the smallest bipartite non-planar graph — as (from, to) pairs."""
	return [(u, v) for u in ("u1", "u2", "u3") for v in ("v1", "v2", "v3")]


class TestCheckTopology(unittest.TestCase):
	def test_a_chain_with_a_branch_is_planar(self):
		topo = check_topology(planar_ir()["flows"])
		self.assertTrue(topo["planar"])
		self.assertEqual(topo["min_crossings"], 0)
		self.assertEqual(topo["obstruction"], [])

	def test_k33_is_not_planar_and_names_the_obstruction(self):
		topo = check_topology(k33_flows())
		self.assertFalse(topo["planar"])
		self.assertEqual(topo["min_crossings"], 1)
		self.assertEqual(set(topo["obstruction"]), {"u1", "u2", "u3", "v1", "v2", "v3"})

	def test_flow_dicts_and_tuples_are_both_accepted(self):
		as_dicts = check_topology([_flow(a, b) for a, b in k33_flows()])
		as_tuples = check_topology(k33_flows())
		self.assertEqual(as_dicts["planar"], as_tuples["planar"])

	def test_self_loops_and_blanks_are_ignored(self):
		topo = check_topology([_flow("a", "a"), _flow("", "b"), _flow("a", "b")])
		self.assertTrue(topo["planar"])

	def test_empty_flows_are_planar(self):
		self.assertTrue(check_topology([])["planar"])


class TestFlowPairsFromXml(unittest.TestCase):
	def test_reads_both_namespace_prefixes(self):
		xml = (
			'<bpmn:sequenceFlow id="f1" sourceRef="a" targetRef="b" />'
			'<bpmn2:sequenceFlow id="f2" name="x" sourceRef="b" targetRef="c"></bpmn2:sequenceFlow>'
		)
		self.assertEqual(flow_pairs_from_xml(xml), [("a", "b"), ("b", "c")])


class TestHints(unittest.TestCase):
	def test_non_planar_hint_tells_the_model_to_stop_regenerating(self):
		self.assertIn("Do not regenerate", _RULE_HINTS["non-planar"])

	def test_layout_rules_are_never_fed_back_as_ir_fixes(self):
		for rule in ("edge-crossing", "edge-through-shape", "collinear-overlap", "label-collision"):
			self.assertIn(rule, _IR_IGNORABLE_RULES)
		hints = translate_problems([{"kind": "layout", "rule": "edge-crossing", "message": "x"}])
		self.assertEqual(hints, [])

	def test_topology_problem_reaches_the_model_as_a_hint(self):
		hints = translate_problems([{"kind": "topology", "rule": "non-planar", "message": "m"}])
		self.assertEqual(len(hints), 1)
		self.assertIn("Do not regenerate", hints[0])


class TestCompileIrEndToEnd(unittest.TestCase):
	"""Runs the real spiff/pipeline.mjs — needs node on PATH."""

	def test_planar_ir_draws_with_no_crossings(self):
		res = compile_ir(planar_ir())
		self.assertTrue(res["ok"], res.get("problems"))
		self.assertTrue(res["topology"]["planar"])
		self.assertEqual(res["layout"]["crossings"], 0, res["layout"])
		self.assertEqual(res["layout"]["throughShape"], 0, res["layout"])
		self.assertEqual([p for p in res["problems"] if p.get("kind") == "topology"], [])

	def test_non_planar_ir_is_reported_not_failed(self):
		nodes = [_node("start", "startEvent")] + [_node(n) for n in ("u1", "u2", "u3")]
		nodes += [_node(n, lane="b") for n in ("v1", "v2", "v3")] + [_node("end", "endEvent", lane="b")]
		flows = [_flow("start", "u1"), _flow("start", "u2"), _flow("start", "u3")]
		flows += [_flow(a, b) for a, b in k33_flows()]
		flows += [_flow("v1", "end"), _flow("v2", "end"), _flow("v3", "end")]
		res = compile_ir({"name": "Tangled", "lanes": LANES, "nodes": nodes, "flows": flows})
		self.assertTrue(res["ok"], res.get("problems"))
		self.assertFalse(res["topology"]["planar"])
		kinds = {p.get("rule") for p in res["problems"]}
		self.assertIn("non-planar", kinds)
		self.assertGreaterEqual(res["layout"]["crossings"], 1)

	def test_lane_less_ir_still_gets_a_drawing(self):
		ir = planar_ir()
		ir.pop("lanes")
		for n in ir["nodes"]:
			n.pop("lane", None)
		res = compile_ir(ir)
		self.assertTrue(res["ok"], res.get("problems"))
		self.assertIn("<bpmndi:BPMNShape", res["xml"])
		self.assertNotIn("Participant", res["xml"])
		self.assertEqual(res["layout"]["crossings"], 0, res["layout"])


if __name__ == "__main__":
	unittest.main()
