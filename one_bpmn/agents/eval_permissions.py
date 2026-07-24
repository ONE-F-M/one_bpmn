"""
WI-001744: permission scoping for the AI Evals doctypes.

A user may see an AI Eval Suite only when they are the process owner of the
suite's process — i.e. Suite.process_model -> BPMN Process Model.process_name
-> Process.process_owner == the user. AI Eval Case and AI Eval Run inherit the
same scope through their ``suite`` link. Only System Manager sees everything.

Suites with no process_model (e.g. agent-baseline suites created before a chat
map exists) have no owner and are therefore visible only to System Manager.

The query-condition helpers build their subquery with frappe.qb (no hand-rolled
SQL) and return the WHERE fragment Frappe ANDs into the list query.
"""

import frappe
from frappe.query_builder import DocType


def _is_system_manager(user: str) -> bool:
	return "System Manager" in frappe.get_roles(user)


def _owned_suites_subquery(user: str) -> str:
	"""SQL selecting the names of AI Eval Suites whose process is owned by ``user``."""
	suite = DocType("AI Eval Suite")
	model = DocType("BPMN Process Model")
	process = DocType("Process")
	q = (
		frappe.qb.from_(suite)
		.inner_join(model).on(model.name == suite.process_model)
		.inner_join(process).on(process.name == model.process_name)
		.select(suite.name)
		.where(process.process_owner == user)
	)
	return q.get_sql()


def _process_model_owned_by(process_model: str, user: str) -> bool:
	if not process_model:
		return False
	process = frappe.db.get_value("BPMN Process Model", process_model, "process_name")
	if not process:
		return False
	return frappe.db.get_value("Process", process, "process_owner") == user


def _suite_owned_by(suite: str, user: str) -> bool:
	if not suite:
		return False
	return _process_model_owned_by(
		frappe.db.get_value("AI Eval Suite", suite, "process_model"), user
	)


# ── AI Eval Suite ────────────────────────────────────────────────────────────
def eval_suite_query_conditions(user: str = None) -> str:
	user = user or frappe.session.user
	if _is_system_manager(user):
		return ""
	return f"`tabAI Eval Suite`.`name` in ({_owned_suites_subquery(user)})"


def eval_suite_has_permission(doc, ptype=None, user: str = None) -> bool:
	user = user or frappe.session.user
	if _is_system_manager(user):
		return True
	return _process_model_owned_by(getattr(doc, "process_model", None), user)


# ── AI Eval Case ─────────────────────────────────────────────────────────────
def eval_case_query_conditions(user: str = None) -> str:
	user = user or frappe.session.user
	if _is_system_manager(user):
		return ""
	return f"`tabAI Eval Case`.`suite` in ({_owned_suites_subquery(user)})"


def eval_case_has_permission(doc, ptype=None, user: str = None) -> bool:
	user = user or frappe.session.user
	if _is_system_manager(user):
		return True
	return _suite_owned_by(getattr(doc, "suite", None), user)


# ── AI Eval Run ──────────────────────────────────────────────────────────────
def eval_run_query_conditions(user: str = None) -> str:
	user = user or frappe.session.user
	if _is_system_manager(user):
		return ""
	return f"`tabAI Eval Run`.`suite` in ({_owned_suites_subquery(user)})"


def eval_run_has_permission(doc, ptype=None, user: str = None) -> bool:
	user = user or frappe.session.user
	if _is_system_manager(user):
		return True
	return _suite_owned_by(getattr(doc, "suite", None), user)
