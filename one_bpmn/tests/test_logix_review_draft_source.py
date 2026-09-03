# Copyright (c) 2026, one-fm and contributors
"""Logix's reviewer must find the draft whichever way the write step wrote it.

Two shapes exist across sites — a Script Task writing ``turn["draft"]`` and an
AI Agent Task whose result is auto-persisted under its own bpmn_id. A reviewer
that reads only one of them reviews an empty string and the turn ends with no
reply, which is what both live failures looked like.
"""

import ast
import unittest

from one_bpmn.one_bpmn.patches.v1_0.logix_review_reads_either_draft_source import (
	_MARKER,
	_NEW,
	_OLD,
)

# What the AI-Agent-Task-only reviewer looks like before the patch.
BEFORE = f'''import json
turn = get_turn(context_docname)
{_OLD}
shape_kind = (turn.get("process_context") or {{}}).get("shape_kind") or "script_task"
'''


def _apply(script):
	if _MARKER in script or _OLD not in script:
		return script
	return script.replace(_OLD, _NEW, 1)


class TestLogixReviewDraftSource(unittest.TestCase):
	def test_patched_script_reads_both_sources(self):
		out = _apply(BEFORE)
		self.assertIn('turn.get("draft")', out)
		self.assertIn("write_script_result", out)
		self.assertIn("write_agent_tool_result", out)
		ast.parse(out)

	def test_it_is_idempotent(self):
		once = _apply(BEFORE)
		self.assertEqual(_apply(once), once)

	def test_the_other_variant_is_left_alone(self):
		"""The Script-Task-only form belongs to the other patch."""
		other = 'turn = get_turn(context_docname)\ndraft = turn.get("draft", "")\n'
		self.assertEqual(_apply(other), other)

	def test_draft_resolution_prefers_the_writer_that_ran(self):
		"""Whichever key holds text wins; a missing one never shadows it."""
		def resolve(turn):
			return (
				turn.get("draft")
				or (turn.get("write_script_result") or {}).get("write_script_output")
				or (turn.get("write_agent_tool_result") or {}).get("write_agent_tool_output")
				or ""
			)

		self.assertEqual(resolve({"draft": "script-task draft"}), "script-task draft")
		self.assertEqual(
			resolve({"write_script_result": {"write_script_output": "agent draft"}}), "agent draft"
		)
		self.assertEqual(
			resolve({"write_agent_tool_result": {"write_agent_tool_output": "tool draft"}}),
			"tool draft",
		)
		self.assertEqual(resolve({}), "")
		# an empty string from one source must not hide a real draft in another
		self.assertEqual(
			resolve({"draft": "", "write_script_result": {"write_script_output": "real"}}), "real"
		)
