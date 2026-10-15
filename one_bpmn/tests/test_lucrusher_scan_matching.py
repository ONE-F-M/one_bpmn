# Copyright (c) 2026, one-fm and contributors
# License: MIT. See license.txt
"""The LuCrusher scan patch, run against the BA site's copies of the scripts."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from frappe.tests.utils import FrappeTestCase

from one_bpmn.one_bpmn.patches.v1_0 import lucrusher_scan_counts_and_matching as p

FIXTURES = Path(__file__).parent / "fixtures"
ELEMENTS = [
	"Create Maintenance Schedule Entry",
	"Generate Work Order",
	"Create Maintenance Plan",
	"Generate Maintenance KPI Assessment",
]


def _fixture(name):
	return (FIXTURES / name).read_text(encoding="utf-8")


def _doctype(name, app="one_fm"):
	slug = name.lower().replace(" ", "_")
	return {
		"name": name,
		"app": app,
		"module": "One Fm",
		"file": f"{app}/{slug}.json",
		"py_file": f"{app}/{slug}.py",
		"py_exists": True,
	}


def _hook(doctype, method, event="on_update", hook_type="doc_events"):
	return {"hook_type": hook_type, "doctype": doctype, "event": event, "method": method, "app": "one_fm"}


def _run_scan(doctypes, hooks):
	"""Run the patched scan script with split globals and locals, as a Script Task does.

	Returns the digest the model sees and the full scan stored for the turn.
	"""
	script, changed = p.apply_edits(_fixture("lucrusher_scan_codebase_ba.txt"), p.SCAN_EDITS, p.SCAN_MARKER)
	assert changed
	index = {"doctypes": doctypes, "hooks": hooks, "apps_scanned": ["frappe", "one_fm"]}
	scope = {
		"frappe": SimpleNamespace(log_error=lambda **kw: None, get_traceback=lambda: ""),
		"task_data": {"process_elements": ELEMENTS},
		"context_docname": "x",
		"result": {},
	}
	stored = {}
	with (
		patch("one_bpmn.agents.codebase_index.get_codebase_index", return_value=index),
		patch("one_bpmn.agents.codebase_index.find_whitelisted_methods", return_value=[]),
		patch("one_bpmn.agents.turn_state.update_turn", side_effect=lambda _name, **kw: stored.update(kw)),
	):
		exec(script, scope, {})  # noqa: S102 - the patched script text under test
	return scope["result"]["codebase_scan"], stored["full_scan"]


class TestScanMatching(FrappeTestCase):
	def test_generic_word_alone_does_not_match(self):
		_, full = _run_scan([_doctype("Maintenance Frequency"), _doctype("Maintenance Schedule Entry")], [])
		self.assertEqual([d["doctype"] for d in full["matched_doctypes"]], ["Maintenance Schedule Entry"])

	def test_matched_doctype_has_an_app_and_its_controller_is_listed(self):
		digest, full = _run_scan([_doctype("Maintenance Schedule Entry")], [])
		self.assertGreater(digest["counts"]["controllers"], 0)
		self.assertEqual([c["doctype"] for c in full["controller_classes"]], ["Maintenance Schedule Entry"])
		self.assertTrue(all(d["app"] for d in full["matched_doctypes"]))

	def test_hook_on_star_never_appears_and_scheduler_hook_does(self):
		hooks = [
			_hook("*", "one_fm.x.generate_work_order_sync"),
			_hook("", "one_fm.x.generate_due_work_orders", event="daily", hook_type="scheduler_events"),
		]
		_, full = _run_scan([_doctype("Maintenance Schedule Entry")], hooks)
		methods = [h["method"] for h in full["hooks_found"]]
		self.assertEqual(methods, ["one_fm.x.generate_due_work_orders"])

	def test_counts_are_real_totals_not_the_caps(self):
		letters = "abcdefghijklmnopqrstuvwxyz"
		doctypes = [_doctype(f"Work Order Zz{letters[i // 26]}{letters[i % 26]}") for i in range(100)]
		digest, full = _run_scan(doctypes, [])
		self.assertEqual(digest["counts"]["doctypes"], 100)
		self.assertEqual(full["shown"]["doctypes"], 60)
		self.assertIn("DocTypes 60 of 100 shown", digest["counts_line"])


class TestPatchEdits(FrappeTestCase):
	def test_each_script_takes_its_edit_once(self):
		for fixture, edits, marker in (
			("lucrusher_scan_codebase_ba.txt", p.SCAN_EDITS, p.SCAN_MARKER),
			("lucrusher_save_response_ba.txt", p.SAVE_EDITS, p.SAVE_MARKER),
			("lucrusher_build_context_ba.txt", p.CONTEXT_EDITS, p.CONTEXT_MARKER),
		):
			updated, changed = p.apply_edits(_fixture(fixture), edits, marker)
			self.assertTrue(changed, fixture)
			compile(updated, fixture, "exec")
			self.assertEqual(p.apply_edits(updated, edits, marker), (updated, False))

	def test_moved_anchor_leaves_the_script_alone(self):
		text = "result = 1\n"
		self.assertEqual(p.apply_edits(text, p.SCAN_EDITS, p.SCAN_MARKER), (text, False))

	def test_prompt_gains_the_sources_rule_once(self):
		prompt, changed = p.with_sources_block(_fixture("lucrusher_prompt_ba.txt"))
		self.assertTrue(changed)
		self.assertIn("Never attribute a figure to another engagement", prompt)
		self.assertIn("unless the user asks for a re-run", prompt)
		self.assertIn("N of M shown", prompt)
		self.assertEqual(p.with_sources_block(prompt), (prompt, False))

	def test_build_context_quotes_the_scan_line(self):
		script, _ = p.apply_edits(_fixture("lucrusher_build_context_ba.txt"), p.CONTEXT_EDITS, p.CONTEXT_MARKER)
		self.assertIn('scan.get("counts_line")', script)
		self.assertIn("scan tool result", script)
