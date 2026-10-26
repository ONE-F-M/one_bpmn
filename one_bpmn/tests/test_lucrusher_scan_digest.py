# Copyright (c) 2026, one-fm and contributors
# License: MIT. See license.txt
"""WI-002195: the LuCrusher patch, exercised as it will run.

The scan digest is executed straight out of the text the patch installs — with
the same split globals/locals the shape-tool exec uses — against a scan the size
of the real ones, so the test proves the reduction rather than asserting a
string was replaced. The prompt block is checked for idempotence. When the site
carries the script the patch targets, the edit is also applied to that real
text and shown to be a one-time, anchored change.
"""

from __future__ import annotations

import json

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.one_bpmn.patches.v1_0.lucrusher_scan_digest_and_short_confirmations import (
	_PROMPT_BLOCK,
	_SCAN_MARKER,
	_SCAN_NEW,
	_SCAN_OLD,
	_SCAN_SCRIPT,
	apply_scan_digest,
	with_confirmation_block,
)


def _digest_function():
	"""The installed digest, executed the way the engine executes a Script Task
	def: the function body may see only its own arguments."""
	source = _SCAN_NEW.split('\n\nresult["codebase_scan"]')[0]
	namespace: dict = {}
	exec(source, {"__builtins__": __builtins__}, namespace)  # noqa: S102 - the patch's own text
	return namespace["_lucrusher_scan_digest"]


def _trim_function():
	"""The trimmer the digest replaces, for the before/after measurement."""
	source = (
		"def _lucrusher_trim_scan(scan):\n"
		"    if not scan or scan.get('error'):\n"
		"        return scan\n"
		"    trimmed = dict(scan)\n"
		"    for key in ('matched_doctypes', 'doctypes_found', 'hooks_found',\n"
		"                'controller_files', 'controller_classes',\n"
		"                'whitelist_methods', 'whitelisted_methods'):\n"
		"        items = scan.get(key) or []\n"
		"        if len(items) > 20:\n"
		"            trimmed[key] = items[:20]\n"
		"            trimmed[key + '_truncated'] = True\n"
		"            trimmed[key + '_total'] = len(items)\n"
		"    return trimmed\n"
	)
	namespace: dict = {}
	exec(source, {"__builtins__": __builtins__}, namespace)  # noqa: S102
	return namespace["_lucrusher_trim_scan"]


def _realistic_scan():
	"""Shaped like a real scan: 60 doctypes, 120 hooks, 30 controllers and 60
	methods, every row carrying the file paths and match lists the tool emits."""
	doctypes = [
		{
			"doctype": f"Leave Application Variant {i}",
			"app": "hrms",
			"module": "HR",
			"file": f"apps/hrms/hrms/hr/doctype/leave_application_{i}/leave_application_{i}.json",
			"py_file": f"apps/hrms/hrms/hr/doctype/leave_application_{i}/leave_application_{i}.py",
			"py_exists": True,
			"matched_elements": ["Submit Leave Application", "Approve Leave", "Notify Employee"],
			"score": round(1 - i / 100, 3),
		}
		for i in range(60)
	]
	hooks = [
		{
			"hook_type": "doc_events",
			"doctype": f"Leave Application Variant {i % 60}",
			"event": "on_submit",
			"method": f"hrms.hr.doctype.leave_application_{i % 60}.leave_application_{i % 60}.on_submit_hook_{i}",
			"app": "hrms",
			"matched_elements": ["Submit Leave Application"],
			"score": 0.5,
		}
		for i in range(120)
	]
	controllers = [
		{
			"class": f"LeaveApplicationVariant{i}",
			"doctype": f"Leave Application Variant {i}",
			"file": doctypes[i]["py_file"],
			"app": "hrms",
			"matched_elements": doctypes[i]["matched_elements"],
			"score": doctypes[i]["score"],
		}
		for i in range(30)
	]
	methods = [
		{
			"function": f"get_leave_balance_on_{i}",
			"file": f"apps/hrms/hrms/hr/doctype/leave_application_{i}/leave_application_{i}.py",
			"line": 40 + i,
			"app": "hrms",
			"matched_elements": ["Approve Leave"],
			"score": 0.4,
		}
		for i in range(60)
	]
	summary = "Scanned 3 app(s): hrms, erpnext, one_fm.\n" + "\n".join(
		f"  • **{d['doctype']}** (hrms) — via: \"Submit Leave Application\"" for d in doctypes[:20]
	)
	return {
		"process_elements": ["Submit Leave Application", "Approve Leave", "Notify Employee"],
		"doctypes_found": doctypes,
		"matched_doctypes": doctypes,
		"hooks_found": hooks,
		"controller_classes": controllers,
		"controller_files": controllers,
		"whitelisted_methods": methods,
		"whitelist_methods": methods,
		"summary": summary,
		"apps_scanned": ["hrms", "erpnext", "one_fm"],
		"error": None,
	}


class TestScanDigest(FrappeTestCase):
	def test_digest_is_a_fraction_of_what_the_trimmer_sent(self):
		scan = _realistic_scan()
		before = len(json.dumps(_trim_function()(scan), default=str))
		after = len(json.dumps(_digest_function()(scan), default=str))
		self.assertGreater(before, 30000, "fixture is not the size of a real scan")
		self.assertLess(after, before * 0.15)

	def test_digest_keeps_what_the_model_acts_on(self):
		digest = _digest_function()(_realistic_scan())
		self.assertIn("Leave Application Variant 0", digest["summary"])
		self.assertEqual(digest["counts"], {"doctypes": 60, "hooks": 120, "controllers": 30, "whitelisted_methods": 60})
		self.assertEqual(len(digest["top_doctypes"]), 10)
		self.assertEqual(digest["top_doctypes"][0]["doctype"], "Leave Application Variant 0")
		self.assertEqual(digest["top_whitelisted_methods"][0]["function"], "get_leave_balance_on_0")
		self.assertIn("do not pass it to finalize", digest["note"])
		self.assertIsNone(digest["error"])
		# The rows the frontend reads come from finalize's full copy, not from here.
		self.assertNotIn("matched_doctypes", digest)
		self.assertNotIn("hooks_found", digest)

	def test_errors_and_empty_scans_pass_through(self):
		digest = _digest_function()
		failed = {"error": "index failed", "summary": "Failed", "doctypes_found": []}
		self.assertIs(digest(failed), failed)
		self.assertIsNone(digest(None))

	def test_digest_function_uses_only_its_argument(self):
		"""Split globals/locals: a top-level def in a Script Task cannot see other
		top-level names. The function must run with an empty global scope."""
		source = _SCAN_NEW.split('\n\nresult["codebase_scan"]')[0]
		namespace: dict = {}
		exec(source, {"__builtins__": {"len": len, "isinstance": isinstance, "list": list, "dict": dict}}, namespace)  # noqa: S102
		out = namespace["_lucrusher_scan_digest"](_realistic_scan())
		self.assertEqual(out["counts"]["doctypes"], 60)


class TestScriptEdit(FrappeTestCase):
	def test_edit_is_anchored_and_applied_once(self):
		text = "# header\n\ndef _lucrusher_trim_scan(scan):\n    return scan\n\n\n" + _SCAN_OLD + "\n"
		updated, changed = apply_scan_digest(text)
		self.assertTrue(changed)
		self.assertIn(_SCAN_MARKER, updated)
		self.assertNotIn(_SCAN_OLD, updated)
		self.assertIn('result["codebase_scan"] = _lucrusher_scan_digest(_lcr_full_scan)', updated)
		again, changed_again = apply_scan_digest(updated)
		self.assertFalse(changed_again)
		self.assertEqual(again, updated)

	def test_unrelated_text_is_left_alone(self):
		text = "result['something_else'] = 1\n"
		self.assertEqual(apply_scan_digest(text), (text, False))

	def test_the_real_script_on_this_site_takes_the_edit(self):
		script = frappe.db.get_value("Server Script", _SCAN_SCRIPT, "script")
		if not script:
			self.skipTest("this site does not carry the LuCrusher scan script")
		if _SCAN_MARKER in script:
			# Already patched here: the edit must then be a no-op.
			self.assertEqual(apply_scan_digest(script), (script, False))
			return
		self.assertIn(_SCAN_OLD, script, "the anchor the patch relies on has moved")
		updated, changed = apply_scan_digest(script)
		self.assertTrue(changed)
		compile(updated, _SCAN_SCRIPT, "exec")


class TestConfirmationBlock(FrappeTestCase):
	def test_appended_once(self):
		first, changed = with_confirmation_block("You are LuCrusher.")
		self.assertTrue(changed)
		self.assertTrue(first.startswith("You are LuCrusher."))
		self.assertIn(_PROMPT_BLOCK, first)
		second, changed_again = with_confirmation_block(first)
		self.assertFalse(changed_again)
		self.assertEqual(second, first)

	def test_empty_prompt_gets_the_block_alone(self):
		text, changed = with_confirmation_block("")
		self.assertTrue(changed)
		self.assertTrue(text.startswith("## Confirming a draft"))

	def test_block_names_the_three_confirmation_intents_and_the_two_arguments(self):
		for word in ("TOPOLOGY_CONFIRMED", "MIGRATION_TASKS_CONFIRMED", "PROSALLY_PROMPT_CONFIRMED", "ONLY intent and response"):
			self.assertIn(word, _PROMPT_BLOCK)
