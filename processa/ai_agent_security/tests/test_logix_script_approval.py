# Copyright (c) 2026, one-fm and contributors
"""Logix reads each finding with its approval state, raises a request, and lets flagged scripts through review."""

import frappe
from frappe.tests.utils import FrappeTestCase

from processa.ai_agent_security.code_checks.script_categories import clear_category_cache
from processa.ai_agent_security.code_checks.script_validator import validate_script
from processa.api.script_approvals import lint_server_script, request_script_approval
from processa.patches.v1_0 import logix_review_passes_items_needing_approval as p
from processa.patches.v1_0 import seed_script_import_categories

PROCESS = "Logix Approval Test Process"
SCRIPT = "Logix Approval Test Script"
TASK = "Activity_rates"
CODE = "x = 1\ny = 2\nimport requests\nresult['ok'] = 1"
READER = "logix-approval-reader@example.com"

REVIEW_STUB = """_vres = validate_script(code)
_violations = _vres.get("violations", []) or []
_valid = bool(_vres.get("valid"))
candidate = draft
if _valid:
    _rev2 = validate_script(code)
    if bool(_rev2.get("valid")):
        candidate = draft
    update_turn(context_docname, final=candidate, modified_code=code, script_safe=True, violations=[], findings=[])
    result["approved"] = True
else:
    update_turn(context_docname, violations=_violations, script_safe=False, security_retries=1)
    result["approved"] = False
"""

FINALIZE_STUB = """_vres = validate_script(code)
if _vres.get("valid"):
    update_turn(context_docname, script_safe=True)
else:
    update_turn(context_docname, script_safe=False)
"""


class TestLogixScriptApproval(FrappeTestCase):
	def setUp(self):
		super().setUp()
		clear_category_cache()
		seed_script_import_categories.execute()
		if not frappe.db.exists("Process", PROCESS):
			frappe.get_doc(
				{
					"doctype": "Process",
					"process_name": PROCESS,
					"description": PROCESS,
					"process_owner": "Administrator",
				}
			).insert()
		_server_script(SCRIPT, CODE)
		if not frappe.db.exists("User", READER):
			frappe.get_doc(
				{
					"doctype": "User",
					"email": READER,
					"first_name": "Reader",
					"send_welcome_email": 0,
					"roles": [{"role": "Blogger"}],
				}
			).insert()

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.rollback()
		clear_category_cache()
		super().tearDown()

	def _finding(self, result, name):
		return next(f for f in result["findings"] if f["name"] == name)

	def test_lint_reports_category_line_and_that_it_is_not_approved(self):
		result = lint_server_script(CODE, SCRIPT, PROCESS, TASK)
		finding = self._finding(result, "requests")
		self.assertEqual((finding["category"], finding["line"], finding["approved"]), ("Network", 3, False))
		self.assertIn("BPMN Connector operation", finding["sanctioned_alternative"])
		self.assertEqual(result["status"], "Needs approval")
		self.assertFalse(result["valid"])

	def test_lint_marks_an_approved_item_with_its_request(self):
		request = request_script_approval(SCRIPT, PROCESS, TASK, "Fetches exchange rates")
		frappe.db.set_value("Script Approval Request", request["name"], "status", "Approved")
		result = lint_server_script(CODE, SCRIPT, PROCESS, TASK)
		finding = self._finding(result, "requests")
		self.assertEqual((finding["approved"], finding["request"]), (True, request["name"]))
		self.assertEqual(result["status"], "Approved")
		self.assertTrue(result["valid"])

	def test_lint_without_a_script_uses_the_default_categories(self):
		result = lint_server_script(CODE)
		self.assertFalse(self._finding(result, "requests")["approved"])
		self.assertIsNone(result["open_request"])

	def test_lint_refuses_a_user_who_cannot_read_the_script(self):
		frappe.set_user(READER)
		with self.assertRaises(frappe.PermissionError):
			lint_server_script(CODE, SCRIPT, PROCESS, TASK)

	def test_request_approval_creates_a_request_from_the_saved_script(self):
		result = request_script_approval(SCRIPT, PROCESS, TASK, "Fetches exchange rates")
		request = frappe.get_doc("Script Approval Request", result["name"])
		self.assertEqual(request.script_at_time_of_request, CODE)
		self.assertEqual(request.reason, "Fetches exchange rates")
		self.assertEqual(lint_server_script(CODE, SCRIPT, PROCESS, TASK)["open_request"], request.name)

	def test_request_approval_needs_a_reason(self):
		with self.assertRaises(frappe.ValidationError) as caught:
			request_script_approval(SCRIPT, PROCESS, TASK, "  ")
		self.assertIn("why", str(caught.exception))

	def test_request_approval_refuses_an_open_request_and_a_clean_task(self):
		first = request_script_approval(SCRIPT, PROCESS, TASK, "Fetches exchange rates")
		with self.assertRaises(frappe.ValidationError) as caught:
			request_script_approval(SCRIPT, PROCESS, TASK, "Again")
		self.assertIn(first["name"], str(caught.exception))
		_server_script(SCRIPT, "result['ok'] = 1")
		with self.assertRaises(frappe.ValidationError) as caught:
			request_script_approval(SCRIPT, PROCESS, "Activity_other", "Nothing")
		self.assertIn("nothing that needs approval", str(caught.exception))

	def test_request_approval_refuses_a_user_who_cannot_write_the_script(self):
		frappe.set_user(READER)
		with self.assertRaises(frappe.PermissionError):
			request_script_approval(SCRIPT, PROCESS, TASK, "Fetches exchange rates")

	def test_request_approval_is_post_only(self):
		self.assertEqual(frappe.allowed_http_methods_for_whitelisted_func[request_script_approval], ["POST"])


class TestLogixReviewPassesItemsNeedingApproval(FrappeTestCase):
	def setUp(self):
		super().setUp()
		clear_category_cache()
		seed_script_import_categories.execute()
		_server_script(p.REVIEW_SCRIPT, REVIEW_STUB)
		_server_script(p.FINALIZE_SCRIPT, FINALIZE_STUB)

	def tearDown(self):
		frappe.db.rollback()
		clear_category_cache()
		super().tearDown()

	def _run(self, script_name, code):
		writes, result = {}, {}
		scope = {
			"code": code,
			"draft": f"```python\n{code}\n```",
			"context_docname": "conv",
			"result": result,
			"validate_script": validate_script,
			"update_turn": lambda _conv, **kw: writes.update(kw),
		}
		exec(frappe.db.get_value("Server Script", script_name, "script"), scope)
		return writes, result

	def test_a_script_needing_approval_is_returned_with_the_items_named(self):
		p.execute()
		writes, result = self._run(p.REVIEW_SCRIPT, CODE)
		self.assertTrue(result["approved"])
		self.assertTrue(writes["script_safe"])
		self.assertNotIn("security_retries", writes)
		self.assertIn("needs approval before it can run: requests (Network)", writes["final"])

	def test_a_script_with_a_syntax_error_is_sent_back(self):
		p.execute()
		writes, result = self._run(p.REVIEW_SCRIPT, "result['x'] = (")
		self.assertFalse(result["approved"])
		self.assertEqual(writes["security_retries"], 1)

	def test_finalize_refuses_only_code_that_does_not_parse(self):
		p.execute()
		self.assertTrue(self._run(p.FINALIZE_SCRIPT, CODE)[0]["script_safe"])
		self.assertFalse(self._run(p.FINALIZE_SCRIPT, "result['x'] = (")[0]["script_safe"])

	def test_running_twice_changes_nothing(self):
		p.execute()
		first = frappe.db.get_value("Server Script", p.REVIEW_SCRIPT, "script")
		p.execute()
		self.assertEqual(frappe.db.get_value("Server Script", p.REVIEW_SCRIPT, "script"), first)

	def test_a_script_missing_an_anchor_is_left_as_it_is(self):
		frappe.db.set_value("Server Script", p.FINALIZE_SCRIPT, "script", "result['x'] = 1")
		p.execute()
		self.assertEqual(frappe.db.get_value("Server Script", p.FINALIZE_SCRIPT, "script"), "result['x'] = 1")


def _server_script(name, body):
	if frappe.db.exists("Server Script", name):
		frappe.db.set_value("Server Script", name, "script", body)
		return
	frappe.get_doc(
		{
			"doctype": "Server Script",
			"name": name,
			"script_type": "API",
			"api_method": frappe.scrub(name),
			"script": body,
		}
	).insert()
