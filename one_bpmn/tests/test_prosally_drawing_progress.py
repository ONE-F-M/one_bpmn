# Copyright (c) 2026, one-fm and contributors
"""A drawing reports which part it is on, and a quiet stretch inside a part repeats that line within 30 seconds."""

import ast
import json
from unittest import mock

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.agents import agui_contract, turn_signal
from one_bpmn.agents.turn_state import clear_turn, set_turn
from one_bpmn.one_bpmn.patches.v1_0 import prosally_generate_process_splits_cut_off_phases as split_patch
from one_bpmn.one_bpmn.patches.v1_0 import prosally_reports_drawing_progress as progress_patch
from one_bpmn.one_bpmn.patches.v1_0.prosally_scope_modify_to_subprocess import with_edits
from one_bpmn.tests.test_prosally_generate_process_splits import SHAPES, _is_full_attempt, _script, run_generate

PUBLISH = "one_bpmn.agents.turn_signal.publish_progress"
CONVERSATION = "_test_prosally_drawing_progress"
GENERATE_EDITS = progress_patch.SCRIPTS["ProsAlly%Tool Generate Process"][0]


def _with_progress(text):
	return with_edits(text, GENERATE_EDITS)


class TestPublishProgress(FrappeTestCase):
	def test_the_line_goes_to_the_instance_the_request_is_waiting_on(self):
		frappe.flags[turn_signal.LIVE_TEXT_INSTANCE_FLAG] = "INST-1"
		try:
			with mock.patch.object(turn_signal, "publish_event") as publish_event:
				turn_signal.publish_progress("Drawing part 2 of 6: Review", 2, 6)
		finally:
			frappe.flags[turn_signal.LIVE_TEXT_INSTANCE_FLAG] = None
		instance, event = publish_event.call_args.args
		self.assertEqual(instance, "INST-1")
		self.assertEqual(event["name"], "onefm.progress")
		self.assertEqual(event["value"], {"phase": 2, "total": 6, "message": "Drawing part 2 of 6: Review"})

	def test_nothing_is_sent_when_no_request_is_waiting(self):
		frappe.flags[turn_signal.LIVE_TEXT_INSTANCE_FLAG] = None
		with mock.patch.object(turn_signal, "publish_event") as publish_event:
			turn_signal.publish_progress("Drawing the process")
		publish_event.assert_not_called()

	def test_a_published_line_comes_out_of_consume_before_the_end_marker(self):
		name = "_test_progress_instance"
		turn_signal.clear(name)
		frappe.flags[turn_signal.LIVE_TEXT_INSTANCE_FLAG] = name
		try:
			turn_signal.publish_progress("Drawing part 1 of 2: A", 1, 2)
			turn_signal.publish_progress("Drawing part 2 of 2: B", 2, 2)
			turn_signal.publish(name)
			events = list(turn_signal.consume(name, 5))
		finally:
			frappe.flags[turn_signal.LIVE_TEXT_INSTANCE_FLAG] = None
			turn_signal.clear(name)
		self.assertEqual(
			[(e["name"], e["value"]["message"]) for e in events],
			[("onefm.progress", "Drawing part 1 of 2: A"), ("onefm.progress", "Drawing part 2 of 2: B")],
		)

	def test_the_event_matches_the_contract(self):
		example = {"phase": 2, "total": 6, "message": "Drawing part 2 of 6: Review"}
		self.assertEqual(agui_contract.validate_event("onefm.progress", example), [])
		self.assertTrue(agui_contract.validate_event("onefm.progress", {"phase": 2}))
		self.assertTrue(agui_contract.validate_event("onefm.progress", {"message": "x", "other": 1}))


class FakeClock:
	"""Time that only moves when the fake wait runs out its window."""

	def __init__(self):
		self.now = 0.0

	def monotonic(self):
		return self.now


class TestAQuietPartRepeatsItsLine(FrappeTestCase):
	def _consume(self, queue, still_running=lambda: True, idle_seconds=60):
		clock = FakeClock()
		windows = []

		def pop_before(key, window):
			windows.append(window - clock.now)
			if queue:
				return queue.pop(0)
			clock.now = window
			return None

		with (
			mock.patch.object(turn_signal.time, "monotonic", clock.monotonic),
			mock.patch.object(turn_signal, "_pop_before", pop_before),
		):
			events = list(
				turn_signal.consume("INST-1", 1800, idle_seconds=idle_seconds, still_running=still_running)
			)
		return events, windows

	def _progress(self, message):
		return json.dumps(
			{"type": "CUSTOM", "name": "onefm.progress", "value": {"phase": 2, "total": 6, "message": message}}
		)

	def test_the_line_is_repeated_with_the_time_spent_every_25_seconds_until_the_job_ends(self):
		running = iter([True, True, False])
		events, windows = self._consume([self._progress("Drawing part 2 of 6: Review")], lambda: next(running))
		messages = [e["value"]["message"] for e in events]
		self.assertEqual(
			messages,
			[
				"Drawing part 2 of 6: Review",
				"Drawing part 2 of 6: Review (still working, 25s)",
				"Drawing part 2 of 6: Review (still working, 50s)",
			],
		)
		self.assertEqual(windows[1:], [25, 25, 25])
		self.assertTrue(all(e["name"] == "onefm.progress" for e in events))
		self.assertEqual(events[1]["value"]["phase"], 2)

	def test_before_any_progress_line_the_general_note_comes_after_the_usual_quiet_minute(self):
		running = iter([True, False])
		events, windows = self._consume([], lambda: next(running))
		self.assertEqual(events[0]["name"], turn_signal.STILL_WORKING_EVENT)
		self.assertEqual(windows[0], 60)

	def test_no_idle_limit_means_no_heartbeat(self):
		events, windows = self._consume(
			[self._progress("Drawing the process")], still_running=lambda: False, idle_seconds=None
		)
		self.assertEqual(len(events), 1)
		self.assertEqual(windows[1], 1800)


class TestTheGenerateScriptReportsEachPart(FrappeTestCase):
	def _run(self, shape, should_cut):
		calls = []
		original = split_patch.rewrite
		with (
			mock.patch.object(split_patch, "rewrite", lambda text: _with_progress(original(text))),
			mock.patch(PUBLISH, lambda *args: calls.append(args)),
		):
			run_generate(shape, should_cut=should_cut)
		return calls

	def test_a_drawing_in_three_parts_says_so_before_each_part(self):
		for shape in SHAPES:
			calls = self._run(shape, _is_full_attempt)
			self.assertEqual(calls[:2], [("Drawing the process",), ("Planning the drawing in parts",)], shape)
			parts = [c for c in calls if c[0].startswith("Drawing part")]
			self.assertEqual(
				parts,
				[
					("Drawing part 1 of 3: Intake", 1, 3),
					("Drawing part 2 of 3: Review", 2, 3),
					("Drawing part 3 of 3: Close", 3, 3),
				],
				shape,
			)

	def test_a_drawing_in_one_pass_says_only_that(self):
		for shape in SHAPES:
			self.assertEqual(self._run(shape, lambda user: False), [("Drawing the process",)], shape)

	def test_the_edited_scripts_still_parse(self):
		for shape in SHAPES:
			ast.parse(_with_progress(split_patch.rewrite(_script(shape))))


class TestTheModifyScriptReportsIt(FrappeTestCase):
	def test_an_edit_says_it_is_updating_the_diagram(self):
		pattern = "ProsAlly%Tool Modify Process"
		name = frappe.db.get_value("Server Script", {"name": ["like", pattern]}, "name")
		if not name:
			self.skipTest("the ProsAlly Modify Process script is not on this site")
		edits, marker = progress_patch.SCRIPTS[pattern]
		live = frappe.db.get_value("Server Script", name, "script")
		script = live if marker in live else with_edits(live, edits)
		xml = (
			'<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL" id="D">'
			'<bpmn:process id="P"><bpmn:userTask id="a" name="Review"/></bpmn:process></bpmn:definitions>'
		)
		set_turn(CONVERSATION, {"user_text": "Add a step", "process_name": "P", "current_xml": xml, "chat_history": []})
		calls = []
		try:
			with (
				mock.patch(PUBLISH, lambda *args: calls.append(args)),
				mock.patch(
					"one_bpmn.agents.prosally_helpers.complete_sub_prompt", return_value='{"nodes": [], "flows": []}'
				),
			):
				exec(script, {"frappe": frappe, "context_docname": CONVERSATION, "result": {}, "bpmn_id": "x"})
		finally:
			clear_turn(CONVERSATION)
		self.assertEqual(calls[0], ("Updating the diagram",))
		self.assertTrue(all(c[0].startswith(("Updating", "Checking")) for c in calls))


class TestProgressPatch(FrappeTestCase):
	def test_every_anchor_is_found_once_and_a_second_run_changes_nothing(self):
		for pattern, (edits, marker) in progress_patch.SCRIPTS.items():
			name = frappe.db.get_value("Server Script", {"name": ["like", pattern]}, "name")
			if not name:
				self.skipTest("the ProsAlly scripts are not on this site")
			progress_patch.execute()
			after = frappe.db.get_value("Server Script", name, "script")
			self.assertIn(marker, after)
			progress_patch.execute()
			self.assertEqual(frappe.db.get_value("Server Script", name, "script"), after)
			ast.parse(after)
