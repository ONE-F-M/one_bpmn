"""
WI-000366: permission scoping for the AI Memory doctype (memory browser).

A user sees an AI Memory row when either is true:
  - it is theirs personally (``AI Memory.user`` == the user), or
  - it belongs to a process they own \u2014 ``AI Memory.process_model`` ->
    ``BPMN Process Model.process_name`` -> ``Process.process_owner`` == the user.
    This covers Process-scoped memories directly, and Agent-scoped memories
    that recorded which process run wrote them (``process_model`` is optional
    provenance on an Agent-scoped row, see ai_memory.json).

System Manager sees everything. Write access (used by retire/restore) is the
same scope as read \u2014 there is no wider write population.

Rows with neither a ``user`` nor a ``process_model`` a user owns (e.g. a
shared Entity-scoped memory with no process link) are visible only to System
Manager, the same "no owner, System-Manager-only" behaviour used for AI Eval
Suite in eval_permissions.py.

Query-condition helpers build their subquery with frappe.qb (no hand-rolled
SQL) and return the WHERE fragment Frappe ANDs into the list query.
"""

import frappe
from frappe.query_builder import DocType


def _is_system_manager(user: str) -> bool:
	return "System Manager" in frappe.get_roles(user)


def _owned_process_models_subquery(user: str) -> str:
	"""SQL selecting the names of BPMN Process Models owned (via Process)
	by ``user``."""
	model = DocType("BPMN Process Model")
	process = DocType("Process")
	q = (
		frappe.qb.from_(model)
		.join(process).on(process.name == model.process_name)
		.select(model.name)
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


def memory_query_conditions(user: str = None) -> str:
	user = user or frappe.session.user
	if _is_system_manager(user):
		return ""
	return (
		f"(`tabAI Memory`.`user` = {frappe.db.escape(user)} "
		f"OR `tabAI Memory`.`process_model` in ({_owned_process_models_subquery(user)}))"
	)


def memory_has_permission(doc, ptype=None, user: str = None) -> bool:
	user = user or frappe.session.user
	if _is_system_manager(user):
		return True
	if getattr(doc, "user", None) == user:
		return True
	return _process_model_owned_by(getattr(doc, "process_model", None), user)
