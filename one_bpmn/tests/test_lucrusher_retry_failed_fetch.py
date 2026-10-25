# Copyright (c) 2026, one-fm and contributors
"""A failed Lucidchart fetch is not stored as a fetched document and can be retried.

The behaviour tests run small stand-ins for the three Server Scripts, built from the
very text the patch anchors on, so they need no live script on the site.

Run with:
    bench --site SITE run-tests --app one_bpmn --module one_bpmn.tests.test_lucrusher_retry_failed_fetch
"""

from __future__ import annotations

import os
from types import SimpleNamespace

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.one_bpmn.patches.v1_0 import lucrusher_retries_a_failed_fetch as patch

TOPOLOGY = "lucrusher-topology-analysis"
UUID = "75d0898c-f3ce-46d7-a242-997a179f09b9"
GOOD_DOC = {"title": "Subcontractor", "page_count": 2, "pages": [{"page_title": "A"}, {"page_title": "B"}]}
ERROR_403 = "Lucidchart API returned 403 Forbidden"

BUILD_CONTEXT_STUB = (
	"_STATE_KEYS = (\n"
	'    "intent", "document",\n'
	'    "topology", "migration_tasks", "prosally_prompts",\n'
	")\n"
	"def _fmt_state(state):\n"
	"    lines = []\n"
	'    doc_obj = state.get("document")\n'
	"    if doc_obj and isinstance(doc_obj, dict):\n"
	'        lines.append("  Lucidchart document : [ALREADY FETCHED - do not re-fetch]")\n'
	"    elif doc_obj:\n"
	'        lines.append("  Lucidchart document : " + str(doc_obj))\n'
	"    else:\n"
	'        lines.append("  Lucidchart document : not yet fetched")\n'
	'    return "\\n".join(lines)\n'
	"_next_skill = _stub_next\n"
	"if _next_skill:\n"
	"    for _phase_skill in sorted(['other']):\n"
	"        deactivate_skill(_phase_skill, None, None)\n"
	"    activate_skill(_next_skill, None, None)\n"
	"result = {'state_block': _fmt_state(context_state), 'preloaded_skill': _next_skill}\n"
)

SAVE_RESPONSE_STUB = (
	"def _pick(key):\n"
	"    new_val = agent_result.get(key)\n"
	"    if new_val in (None, {}, [], ''):\n"
	"        return _prev.get(key)\n"
	"    return new_val\n"
	'_doc = _pick("document")\n'
	"_doc_summary = None\n"
	"_pp = None\n"
	"snapshot = {\n"
	'    "document": _doc,\n'
	'    "prosally_prompts": _pp,\n'
	"}\n"
	"from one_bpmn.agents.memory.session_state import record"
)


def _run_build_context(context_state, stub_next=""):
	code = patch.apply_edits(BUILD_CONTEXT_STUB, patch.BUILD_CONTEXT_EDITS)
	calls = SimpleNamespace(activated=[], deactivated=[])
	scope = {
		"context_state": context_state,
		"_stub_next": stub_next,
		"agent_configuration": None,
		"instance": None,
		"activate_skill": lambda name, *_: calls.activated.append(name),
		"deactivate_skill": lambda name, *_: calls.deactivated.append(name),
	}
	exec(code, scope)  # noqa: S102 - stand-in script text owned by this test
	return scope["result"], calls


def _run_save_response(agent_document, prev):
	code = patch.apply_edits(SAVE_RESPONSE_STUB, patch.SAVE_RESPONSE_EDITS)
	code = code.replace("from one_bpmn.agents.memory.session_state import record", "")
	scope = {"agent_result": {"document": agent_document}, "_prev": prev}
	exec(code, scope)  # noqa: S102 - stand-in script text owned by this test
	return scope["snapshot"]


def _share_hint():
	scope = {}
	exec(patch.SHARE_HINT.replace("def _lucrusher_trim_document(doc):", "pass"), scope)  # noqa: S102
	return scope["_lucrusher_share_hint"]


class TestBuildContext(FrappeTestCase):
	def test_a_failed_fetch_is_retryable_and_names_the_document(self):
		out, _ = _run_build_context({"last_fetch_error": {"document_id": UUID, "error": ERROR_403}})

		self.assertIn(f"fetch failed ({ERROR_403}) - retry allowed", out["state_block"])
		self.assertIn(UUID, out["state_block"])
		self.assertNotIn("ALREADY FETCHED", out["state_block"])

	def test_a_stored_zero_page_document_is_treated_as_failed(self):
		stuck = {"title": UUID, "page_count": 0, "pages": []}

		out, _ = _run_build_context({"document": stuck})

		self.assertIn("fetch failed (the document returned 0 pages) - retry allowed", out["state_block"])
		self.assertIn(UUID, out["state_block"])
		self.assertNotIn("ALREADY FETCHED", out["state_block"])

	def test_a_good_document_still_reads_as_fetched(self):
		out, calls = _run_build_context({"document": GOOD_DOC}, stub_next=TOPOLOGY)

		self.assertIn("ALREADY FETCHED", out["state_block"])
		self.assertEqual(out["preloaded_skill"], TOPOLOGY)
		self.assertNotIn(TOPOLOGY, calls.deactivated)

	def test_a_failed_refresh_keeps_the_good_document(self):
		state = {"document": GOOD_DOC, "last_fetch_error": {"document_id": UUID, "error": ERROR_403}}

		out, _ = _run_build_context(state)

		self.assertIn("ALREADY FETCHED", out["state_block"])

	def test_the_topology_skill_is_not_preloaded_after_a_failed_fetch(self):
		stuck = {"title": UUID, "page_count": 0, "pages": []}

		out, calls = _run_build_context({"document": stuck}, stub_next=TOPOLOGY)

		self.assertEqual(out["preloaded_skill"], "")
		self.assertIn(TOPOLOGY, calls.deactivated)
		self.assertEqual(calls.activated, [])


class TestSaveResponse(FrappeTestCase):
	def test_an_error_is_stored_as_last_fetch_error_not_as_the_document(self):
		failed = {"document_id": UUID, "title": "", "pages": [], "page_count": 0, "error": ERROR_403}

		snapshot = _run_save_response(failed, prev={})

		self.assertIsNone(snapshot["document"])
		self.assertEqual(snapshot["last_fetch_error"], {"document_id": UUID, "error": ERROR_403})

	def test_a_fetch_with_no_pages_is_a_failure_with_a_reason(self):
		empty = {"document_id": UUID, "title": "T", "pages": [], "page_count": 0, "error": None}

		snapshot = _run_save_response(empty, prev={})

		self.assertEqual(snapshot["last_fetch_error"]["error"], "the document returned 0 pages")

	def test_a_failure_keeps_the_previous_good_document(self):
		failed = {"document_id": UUID, "pages": [], "error": ERROR_403}

		snapshot = _run_save_response(failed, prev={"document": GOOD_DOC})

		self.assertEqual(snapshot["document"], GOOD_DOC)

	def test_a_successful_fetch_clears_the_error(self):
		fetched = {"document_id": UUID, "title": "T", "pages": [{"page_title": "A"}], "error": None}
		prev = {"last_fetch_error": {"document_id": UUID, "error": ERROR_403}}

		snapshot = _run_save_response(fetched, prev=prev)

		self.assertIsNone(snapshot["last_fetch_error"])
		self.assertEqual(snapshot["document"], fetched)

	def test_a_turn_with_no_fetch_carries_the_error_forward(self):
		prev = {"last_fetch_error": {"document_id": UUID, "error": ERROR_403}}

		snapshot = _run_save_response(None, prev=prev)

		self.assertEqual(snapshot["last_fetch_error"], prev["last_fetch_error"])


class TestPatchEdits(FrappeTestCase):
	def test_a_script_missing_an_anchor_is_not_edited(self):
		self.assertIsNone(patch.apply_edits("print('no anchors here')", patch.SAVE_RESPONSE_EDITS))

	def test_the_prompt_sentence_follows_the_do_not_rerun_rule(self):
		self.assertTrue(patch.PROMPT_NEW.startswith(patch.PROMPT_ANCHOR))
		self.assertIn("A tool that returned an error is not done; retry it when the user asks.", patch.PROMPT_NEW)

	def test_a_403_hint_gives_the_email_and_how_to_share(self):
		profile = SimpleNamespace(
			integrations=SimpleNamespace(
				utils=SimpleNamespace(make_get_request=lambda url, headers=None: {"email": "key.owner@example.com"})
			)
		)

		text = _share_hint()(profile, "https://api.lucid.co", {})

		self.assertIn("key.owner@example.com", text)
		self.assertIn("Share", text)
		self.assertNotIn("API Integration", text)

	def test_a_403_hint_without_a_profile_still_says_how_to_share(self):
		def lookup_fails(url, headers=None):
			raise ValueError("no User grant")

		logged = []
		fake = SimpleNamespace(
			integrations=SimpleNamespace(utils=SimpleNamespace(make_get_request=lookup_fails)),
			log_error=lambda **kw: logged.append(kw),
			get_traceback=lambda: "",
		)

		text = _share_hint()(fake, "https://api.lucid.co", {})

		self.assertIn("Share", text)
		self.assertEqual(len(logged), 1)


class TestPatchOnTheSite(FrappeTestCase):
	def test_running_it_twice_changes_nothing(self):
		names = [patch.BUILD_CONTEXT, patch.SAVE_RESPONSE, patch.FETCH_TOOL]
		if not all(frappe.db.exists("Server Script", n) for n in names):
			self.skipTest("the LuCrusher scripts are not installed on this site")
		patch.execute()
		before = [frappe.db.get_value("Server Script", n, "script") for n in names]

		patch.execute()

		self.assertEqual([frappe.db.get_value("Server Script", n, "script") for n in names], before)
		self.assertIn("last_fetch_error", before[0])

	def test_the_patch_is_declared(self):
		patches = open(os.path.join(frappe.get_app_path("one_bpmn"), "patches.txt")).read()
		self.assertIn("one_bpmn.one_bpmn.patches.v1_0.lucrusher_retries_a_failed_fetch", patches)
