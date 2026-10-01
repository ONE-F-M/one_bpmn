# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""The last earlier-turn message carries a cache marker, so a new turn reads the conversation so far from cache."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

from frappe.tests.utils import FrappeTestCase

from one_bpmn.agents.llm_provider.anthropic_adapter import AnthropicAdapter
from one_bpmn.agents.llm_provider.base import ToolSpec

TOOL = ToolSpec(
	fn=lambda **kw: "ok", name="search", description="Search.", parameters={"q": {"type": "string"}}
)
HISTORY = [
	{"role": "user", "content": "Migrate the visa process."},
	{"role": "assistant", "content": "Found two maps."},
]
TURN = [
	{"role": "user", "content": "Use the newer one."},
	{
		"role": "assistant",
		"content": "",
		"tool_calls": [{"id": "t1", "name": "search", "arguments": {"q": "visa"}}],
	},
	{"role": "tool_results", "results": [{"id": "t1", "name": "search", "content": "Visa v2"}]},
]


class _Stream:
	def __init__(self, sent):
		self.sent = sent

	def __call__(self, **kwargs):
		self.sent.append(kwargs)
		return self

	async def __aenter__(self):
		return self

	async def __aexit__(self, *exc):
		return False

	async def get_final_message(self):
		return SimpleNamespace(
			content=[SimpleNamespace(type="text", text="ok")],
			stop_reason="end_turn",
			usage=SimpleNamespace(input_tokens=1, output_tokens=1),
		)


def _request(transcript: list) -> dict:
	adapter = AnthropicAdapter(api_key="test-key-not-real", model="claude-sonnet-5")
	sent = []
	adapter._client = SimpleNamespace(messages=SimpleNamespace(stream=_Stream(sent)))
	asyncio.run(adapter.step("You migrate processes.", transcript, tools=[TOOL]))
	return sent[0]


def _marked(request: dict) -> list:
	"""(message index, block type) of every cache marker in the conversation."""
	return [
		(i, block["type"])
		for i, message in enumerate(request["messages"])
		for block in message["content"]
		if "cache_control" in block
	]


def _marker_count(request: dict) -> int:
	return (
		len(_marked(request))
		+ sum("cache_control" in t for t in request["tools"])
		+ sum("cache_control" in b for b in request["system"])
	)


class TestTheHistoryMarker(FrappeTestCase):
	def test_the_first_call_of_a_turn_marks_the_last_earlier_turn(self):
		request = _request([*HISTORY, TURN[0]])
		self.assertEqual(_marked(request), [(1, "text")])
		self.assertEqual(request["messages"][1]["content"][-1]["text"], "Found two maps.")

	def test_a_later_call_keeps_it_beside_the_last_tool_result_within_four_markers(self):
		request = _request([*HISTORY, *TURN])
		self.assertEqual(_marked(request), [(1, "text"), (4, "tool_result")])
		self.assertEqual(_marker_count(request), 4)

	def test_a_split_context_prefix_still_fits_within_four_markers(self):
		request = _request(
			[*HISTORY, {"role": "user", "content": "State...\n\nUser message: Use the newer one."}]
		)
		self.assertEqual(_marked(request), [(1, "text"), (2, "text")])
		self.assertEqual(_marker_count(request), 4)

	def test_a_message_added_after_a_tool_result_does_not_move_it(self):
		request = _request([*HISTORY, *TURN, {"role": "user", "content": "Call a tool."}])
		self.assertIn((1, "text"), _marked(request))

	def test_a_first_turn_has_no_history_to_mark(self):
		self.assertEqual(_marked(_request([TURN[0]])), [])
