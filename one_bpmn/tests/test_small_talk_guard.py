# Copyright (c) 2026, one-fm and contributors
"""A greeting must not be mistaken for a specification.

Docu's classifier could only answer CREATE, MODIFY or DISAMBIGUATE, so "hi"
became CREATE and the agent designed a DocType nobody asked for. The test that
now prevents that lives in the map — flat code inside the classify_intent tool
— so these tests execute that block STRAIGHT OUT OF THE PATCH that installs it,
rather than a copy. Its false positives (refusing real work) are the expensive
mistake, so most of what follows guards against them.
"""

import ast
import unittest

from one_bpmn.one_bpmn.patches.v1_0.docu_answers_small_talk import (
	_CLASSIFY_MARKER,
	_CLASSIFY_NEW,
	_CLASSIFY_OLD,
	_GREETING,
	_WRITE_MARKER,
	_WRITE_NEW,
	_WRITE_OLD,
)

_START = "# ── small-talk test: START"
_END = "# ── small-talk test: END ──"


def _verdict(message):
	"""Run the guard exactly as the tool runs it."""
	block = _CLASSIFY_NEW[_CLASSIFY_NEW.index(_START):_CLASSIFY_NEW.index(_END)]
	namespace = {"message": message}
	exec(compile(block, "<small-talk guard>", "exec"), namespace, namespace)
	return namespace["_small_talk"]


class TestSmallTalkGuard(unittest.TestCase):
	def test_greetings_and_acknowledgements_are_small_talk(self):
		for message in (
			"hi", "Hi!", "hello", "Hey there", "yo", "good morning", "thanks",
			"thank you", "ok", "Say OK", "okay, thanks", "are you there", "ping",
			"test", "who are you", "what can you do",
		):
			self.assertTrue(_verdict(message), f"{message!r} should be small talk")

	def test_an_empty_or_wordless_message_is_small_talk(self):
		for message in ("", "   ", "?", "👋"):
			self.assertTrue(_verdict(message), f"{message!r} should be small talk")

	def test_real_requests_are_never_small_talk(self):
		"""The expensive mistake: refusing work the user actually asked for."""
		for message in (
			"I need a DocType to track office equipment",
			"add a status field",
			"leave form",
			"a form to log site inspections with a date, an inspector and a pass/fail result",
			"remove the serial number field",
			"rename it to Equipment Register",
			"hi, can you create a form for blockers",   # a greeting WITH a request
			"ok now add an attachment field",           # an ack WITH a request
			"thanks — one more thing, make the date mandatory",
		):
			self.assertFalse(_verdict(message), f"{message!r} must be treated as real work")

	def test_a_long_message_is_never_small_talk_however_chatty(self):
		self.assertFalse(_verdict("well i am not really sure so how do you do this thing you know"))

	def test_the_guard_runs_before_the_model_is_called(self):
		"""Order is the whole saving: decide first, call the model only if needed."""
		self.assertLess(
			_CLASSIFY_NEW.index(_END),
			_CLASSIFY_NEW.index("run_sync(_adapter.complete"),
			"the small-talk test must be decided before the classifier calls the model",
		)

	def test_the_cheap_path_ends_the_turn_without_a_schema_stage(self):
		cheap = _CLASSIFY_NEW[_CLASSIFY_NEW.index('if intent in _cheap_intents:'):]
		self.assertIn("done=True", cheap)
		self.assertIn("content_free=True", cheap)
		self.assertIn('result["next"] = None', cheap)
		self.assertNotIn("write_schema", cheap.split("else:")[0])

	def test_there_is_always_something_to_say(self):
		self.assertIn("form", _GREETING.lower())
		self.assertGreater(len(_GREETING), 60)


class TestDocuSmallTalkPatch(unittest.TestCase):
	"""The patch is how this reaches a site, so it must be safe to run twice."""

	def test_nothing_python_side_is_required(self):
		"""The whole change lives in the map — no module for a site to deploy."""
		for text in (_CLASSIFY_NEW, _WRITE_NEW):
			self.assertNotIn("one_bpmn.agents.small_talk", text)

	def test_the_scripts_stay_flat(self):
		"""The shape-tool exec splits globals from locals: no def, no lambda, and
		no comprehension — a genuine parse, not a search for the words."""
		for text in (_CLASSIFY_NEW, _WRITE_NEW):
			for node in ast.walk(ast.parse(text)):
				self.assertNotIsInstance(node, ast.FunctionDef)
				self.assertNotIsInstance(node, ast.AsyncFunctionDef)
				self.assertNotIsInstance(node, ast.Lambda)
				self.assertNotIsInstance(node, ast.ListComp)
				self.assertNotIsInstance(node, ast.SetComp)
				self.assertNotIsInstance(node, ast.DictComp)
				self.assertNotIsInstance(node, ast.GeneratorExp)

	def test_script_edits_are_idempotent_and_valid_flat_python(self):
		for old, new, marker in (
			(_CLASSIFY_OLD, _CLASSIFY_NEW, _CLASSIFY_MARKER),
			(_WRITE_OLD, _WRITE_NEW, _WRITE_MARKER),
		):
			script = f"import json\nturn = {{}}\nmessage = ''\nexists = False\ndoctype = ''\nresult = {{}}\n{old}\n"
			once = script.replace(old, new, 1)
			self.assertIn(marker, once)
			twice = once if marker in once else once.replace(old, new, 1)
			self.assertEqual(twice, once, "a second run must change nothing")
			ast.parse(new)

	def test_the_writer_trusts_the_classifier_rather_than_repeating_the_test(self):
		"""One home for the decision: the writer reads content_free off the turn."""
		self.assertIn('turn.get("content_free")', _WRITE_NEW)
		self.assertIn("write_rounds", _WRITE_NEW)
		self.assertNotIn("_chatter", _WRITE_NEW)
