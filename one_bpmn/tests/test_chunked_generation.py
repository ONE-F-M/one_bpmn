# Copyright (c) 2026, one-fm and contributors
"""merge_chunked_ir and chunk_exit_node_id: the pure assembly step behind the
generator's fallback for a process too large for one completion.

Pins that phases concatenate in order into one IR sharing the outline's lane
set, and that the hand-off id between phases is each chunk's last node.
"""

from frappe.tests.utils import FrappeTestCase

from one_bpmn.agents.bpmn_ir_pipeline import chunk_exit_node_id, merge_chunked_ir


class TestMergeChunkedIR(FrappeTestCase):
	def test_concatenates_nodes_and_flows_in_order(self):
		lanes = [{"id": "user", "name": "User"}, {"id": "system", "name": "System (Automatic)"}]
		chunk_1 = {
			"nodes": [{"id": "start", "type": "startEvent"}, {"id": "n1", "type": "userTask"}],
			"flows": [{"from": "start", "to": "n1"}],
		}
		chunk_2 = {
			"nodes": [{"id": "n2", "type": "scriptTask"}, {"id": "end", "type": "endEvent"}],
			"flows": [{"from": "n1", "to": "n2"}, {"from": "n2", "to": "end"}],
		}
		merged = merge_chunked_ir(lanes, [chunk_1, chunk_2])
		self.assertEqual(merged["lanes"], lanes)
		self.assertEqual([n["id"] for n in merged["nodes"]], ["start", "n1", "n2", "end"])
		self.assertEqual(len(merged["flows"]), 3)

	def test_handles_no_chunks(self):
		merged = merge_chunked_ir([], [])
		self.assertEqual(merged["nodes"], [])
		self.assertEqual(merged["flows"], [])


class TestChunkExitNodeId(FrappeTestCase):
	def test_returns_the_last_node_id(self):
		chunk = {"nodes": [{"id": "n1"}, {"id": "n2"}, {"id": "n3"}]}
		self.assertEqual(chunk_exit_node_id(chunk), "n3")

	def test_returns_none_for_an_empty_chunk(self):
		self.assertIsNone(chunk_exit_node_id({"nodes": []}))
		self.assertIsNone(chunk_exit_node_id({}))
