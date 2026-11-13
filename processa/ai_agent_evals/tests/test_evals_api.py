"""Permission and shape tests for the thin api/evals.py endpoints."""

import ast
import inspect
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from processa.api import evals

MAX_ENDPOINT_LINES = 30

# endpoint -> (module the endpoint calls, minimal keyword arguments)
ENDPOINTS = {
	"list_eval_suites": ("suites", {}),
	"get_evals_overview": ("overview", {}),
	"get_suite_detail": ("suites", {"suite": "x"}),
	"create_eval_case": ("case_authoring", {"suite": "x", "title": "t", "input_user_prompt": "p"}),
	"get_eval_case": ("case_authoring", {"name": "x"}),
	"list_conversations_for_case": ("case_authoring", {"suite": "x"}),
	"get_conversation_for_case": ("case_authoring", {"suite": "x", "conversation": "c"}),
	"conversation_context_for_case": (
		"case_authoring",
		{"suite": "x", "conversation": "c", "message": "m"},
	),
	"update_eval_case": ("case_authoring", {"name": "x"}),
	"get_run_review": ("run_review", {"run": "x"}),
	"list_assignable_agents": ("suites", {}),
	"list_owned_processes": ("suites", {}),
	"case_consistency": ("case_authoring", {"suite": "x"}),
	"update_suite_thresholds": ("suites", {"suite": "x"}),
	"reassign_suite": ("suites", {"suite": "x"}),
	"create_suite": ("suites", {"title": "t"}),
	"get_run_comparison": ("run_compare", {"run_a": "x"}),
	"list_comparable_runs": ("run_compare", {"run": "x"}),
	"list_response_feedback": ("feedback", {}),
	"get_feedback_overview": ("feedback", {}),
	"scheduled_results": ("overview", {}),
}
WRITES = ("create_eval_case", "update_eval_case", "update_suite_thresholds", "reassign_suite", "create_suite")
USERS = {
	"System Manager": "evals-sm@example.com",
	"Process Owner": "evals-po@example.com",
	"": "evals-none@example.com",
}


def _make_user(email, role):
	if frappe.db.exists("User", email):
		return
	user = frappe.get_doc({"doctype": "User", "email": email, "first_name": "Evals", "send_welcome_email": 0})
	if role:
		user.append("roles", {"role": role})
	user.insert(ignore_permissions=True)  # perms: test fixture user


class TestEvalsApi(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		for role, email in USERS.items():
			_make_user(email, role)

	def tearDown(self):
		frappe.set_user("Administrator")

	def _call(self, name, user):
		module_name, kwargs = ENDPOINTS[name]
		frappe.set_user(user)
		with patch.object(getattr(evals, module_name), name, return_value={}) as target:
			getattr(evals, name)(**kwargs)
		return target

	def test_every_endpoint_is_listed_here(self):
		defined = {
			n for n, f in inspect.getmembers(evals, inspect.isfunction) if f.__module__ == evals.__name__
		}
		self.assertEqual(defined, set(ENDPOINTS))

	def test_a_user_with_neither_role_gets_a_permission_error(self):
		for name in ENDPOINTS:
			with self.subTest(endpoint=name), self.assertRaises(frappe.PermissionError):
				self._call(name, USERS[""])

	def test_system_manager_and_process_owner_reach_the_module(self):
		for role in ("System Manager", "Process Owner"):
			for name in ENDPOINTS:
				with self.subTest(role=role, endpoint=name):
					self._call(name, USERS[role]).assert_called_once()

	def test_write_endpoints_accept_post_only(self):
		for name in WRITES:
			self.assertEqual(frappe.allowed_http_methods_for_whitelisted_func[getattr(evals, name)], ["POST"])

	def test_every_endpoint_stays_under_the_line_limit_and_calls_ai_agent_evals(self):
		for node in ast.parse(inspect.getsource(evals)).body:
			if not isinstance(node, ast.FunctionDef):
				continue
			first = min([node.lineno] + [d.lineno for d in node.decorator_list])
			self.assertLessEqual(node.end_lineno - first + 1, MAX_ENDPOINT_LINES, node.name)
			self.assertIn(ENDPOINTS[node.name][0], ast.unparse(node), node.name)
