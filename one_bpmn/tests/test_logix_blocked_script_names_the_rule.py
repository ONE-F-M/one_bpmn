# Copyright (c) 2026, one-fm and contributors
"""A blocked Logix script reaches the user with the rule it broke, the line, and the reviewer's safe alternative."""

import json

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.one_bpmn.patches.v1_0 import logix_blocked_script_names_the_rule as p
from one_bpmn.security.script_validator import validate_script

# The stage scripts reduced to the lines the patch anchors on.
REVIEW_STUB = """_vres = validate_script(code)
_violations = _vres["violations"]
candidate = draft
if review_raw:
    _review = json.loads(review_raw)
if True:
    if not _vres["valid"]:
        retries = 1
        update_turn(context_docname, violations=_violations, script_safe=False, security_retries=retries)
        result["violations"] = _violations
    else:
        update_turn(context_docname, final=candidate, modified_code=code, script_safe=True, violations=[])
"""

FINALIZE_STUB = """_REFUSAL = "I was unable to generate a safe script after multiple attempts."
_final_text = "```python\\nx\\n```"
if True:
    if not turn.get("script_safe") and (not _final_text or "```python" in _final_text):
        update_turn(context_docname, output={
            "response": _REFUSAL,
        })
"""

BLOCKED_CODE = "doc = frappe.get_doc('ToDo', 'T1')\ndoc.save(ignore_permissions=True)"
SUGGESTION = "Call doc.save() with no keyword; the script already runs as the acting user."


class TestLogixBlockedScriptNamesTheRule(FrappeTestCase):
	def setUp(self):
		for name in (p.REVIEW_SCRIPT, p.FINALIZE_SCRIPT):
			if not frappe.db.exists("Server Script", name):
				self.skipTest(f"{name} is not on this site")
		frappe.db.set_value("Server Script", p.REVIEW_SCRIPT, "script", REVIEW_STUB)
		frappe.db.set_value("Server Script", p.FINALIZE_SCRIPT, "script", FINALIZE_STUB)

	def _run(self, script_name, **scope):
		writes = {}
		scope.update(
			context_docname="conv",
			result={},
			json=json,
			validate_script=validate_script,
			update_turn=lambda _conv, **kw: writes.update(kw),
		)
		exec(frappe.db.get_value("Server Script", script_name, "script"), scope)
		return writes, scope["result"]

	def test_review_keeps_the_findings_and_the_reviewer_suggestion(self):
		p.execute()
		review = json.dumps({"approved": False, "suggestions": [SUGGESTION]})
		writes, result = self._run(p.REVIEW_SCRIPT, code=BLOCKED_CODE, draft=BLOCKED_CODE, review_raw=review)

		self.assertEqual(writes["findings"][0]["line"], 2)
		self.assertEqual(writes["findings"][0]["code"], "doc.save(ignore_permissions=True)")
		self.assertEqual(writes["review_suggestions"], [SUGGESTION])
		self.assertEqual(result["findings"], writes["findings"])

	def test_review_without_a_reviewer_answer_still_records_the_findings(self):
		p.execute()
		writes, _result = self._run(p.REVIEW_SCRIPT, code=BLOCKED_CODE, draft=BLOCKED_CODE, review_raw="")

		self.assertTrue(writes["findings"])
		self.assertEqual(writes["review_suggestions"], [])

	def test_a_clean_script_clears_the_findings(self):
		p.execute()
		clean = "doc = frappe.get_doc('ToDo', 'T1')\ndoc.save()"
		writes, _result = self._run(p.REVIEW_SCRIPT, code=clean, draft=clean, review_raw="")

		self.assertEqual(writes["findings"], [])

	def test_the_refusal_names_the_rule_quotes_the_line_and_offers_the_alternative(self):
		p.execute()
		finding = validate_script(BLOCKED_CODE)["findings"][0]
		turn = {"script_safe": False, "findings": [finding], "review_suggestions": [SUGGESTION]}
		writes, _result = self._run(p.FINALIZE_SCRIPT, turn=turn)
		response = writes["output"]["response"]

		self.assertIn(finding["rule"], response)
		self.assertIn("line 2: `doc.save(ignore_permissions=True)`", response)
		self.assertIn(SUGGESTION, response)
		self.assertNotIn("unable to generate a safe script", response)

	def test_a_refusal_without_findings_keeps_the_generic_reply(self):
		p.execute()
		writes, _result = self._run(p.FINALIZE_SCRIPT, turn={"script_safe": False})

		self.assertIn("unable to generate a safe script", writes["output"]["response"])

	def test_running_twice_changes_nothing(self):
		p.execute()
		first = frappe.db.get_value("Server Script", p.REVIEW_SCRIPT, "script")
		p.execute()

		self.assertEqual(frappe.db.get_value("Server Script", p.REVIEW_SCRIPT, "script"), first)

	def test_a_script_missing_an_anchor_is_left_as_it_is(self):
		frappe.db.set_value("Server Script", p.FINALIZE_SCRIPT, "script", "result['x'] = 1")
		p.execute()

		self.assertEqual(frappe.db.get_value("Server Script", p.FINALIZE_SCRIPT, "script"), "result['x'] = 1")

	def test_the_reviewer_prompt_asks_for_the_safe_alternative(self):
		name = frappe.db.get_value("AI Agent Configuration", {"agent_id": p.REVIEWER_AGENT_ID}, "name")
		if not name:
			self.skipTest(f"{p.REVIEWER_AGENT_ID} is not on this site")
		frappe.db.set_value(
			"AI Agent Configuration", name, "system_prompt", f"Review it.\n{{\n    {p.REVIEWER_EDIT[0]}\n}}"
		)
		p.execute()

		prompt = frappe.db.get_value("AI Agent Configuration", name, "system_prompt")
		self.assertIn(p.REVIEWER_EDIT[1], prompt)
		self.assertNotIn(p.REVIEWER_EDIT[0], prompt)
