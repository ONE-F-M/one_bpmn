# Copyright (c) 2026, one-fm and contributors
"""ensure_default_lanes: the deterministic fallback that replaces a
repair-pass LLM round-trip when a generated IR is missing its required lanes.

Pins the two outcomes that matter: a fixable IR (has nodes) gets the "User" +
"System (Automatic)" split with every node assigned, and an unfixable one (no
nodes) is left alone, so the caller still sends it back to the model.
"""

from frappe.tests.utils import FrappeTestCase

from one_bpmn.agents.bpmn_ir_pipeline import ensure_default_lanes


class TestEnsureDefaultLanes(FrappeTestCase):
	def test_assigns_user_and_system_lanes_when_missing(self):
		ir = {
			"nodes": [
				{"id": "start", "type": "startEvent", "name": "Start"},
				{"id": "check", "type": "scriptTask", "name": "Check Balance"},
				{"id": "approve", "type": "userTask", "name": "Approve"},
				{"id": "end", "type": "endEvent", "name": "End"},
			],
		}
		changed = ensure_default_lanes(ir)
		self.assertTrue(changed)
		self.assertEqual(
			[l["id"] for l in ir["lanes"]],
			["user", "system"],
		)
		self.assertEqual(ir["nodes"][0]["lane"], "user")  # startEvent
		self.assertEqual(ir["nodes"][1]["lane"], "system")  # scriptTask
		self.assertEqual(ir["nodes"][2]["lane"], "user")  # userTask
		self.assertEqual(ir["nodes"][3]["lane"], "user")  # endEvent

	def test_does_not_overwrite_a_lane_a_node_already_has(self):
		ir = {
			"nodes": [
				{"id": "n1", "type": "scriptTask", "lane": "already_set"},
			],
		}
		ensure_default_lanes(ir)
		self.assertEqual(ir["nodes"][0]["lane"], "already_set")

	def test_leaves_an_already_valid_lane_set_untouched(self):
		ir = {
			"lanes": [{"id": "a", "name": "A"}, {"id": "b", "name": "B"}],
			"nodes": [{"id": "n1", "type": "userTask", "lane": "a"}],
		}
		changed = ensure_default_lanes(ir)
		self.assertFalse(changed)
		self.assertEqual(len(ir["lanes"]), 2)

	def test_does_nothing_when_there_are_no_nodes_to_assign(self):
		"""An empty IR is a deeper generation problem no lane fallback can
		paper over, so the caller must still send it back to the model."""
		ir = {"nodes": []}
		changed = ensure_default_lanes(ir)
		self.assertFalse(changed)
		self.assertNotIn("lanes", ir)
