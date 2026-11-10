"""Queries that feed the cost allocation report."""
from __future__ import annotations

import frappe
from frappe import _
from frappe.query_builder import DocType
from frappe.query_builder import functions as fn
from frappe.utils import add_days, cint, cstr, flt, getdate
from pypika import CustomFunction

from one_bpmn.ai_agent_observability.reports.periods import apply_conditions, origin_condition


# MariaDB month bucketing, used by the cost-allocation report.
DateFormat = CustomFunction("DATE_FORMAT", ["field", "format"])

# Chat Conversation.agent_mode is blank for the general assistant.
GENERAL_CHAT = "General Chat"


def _month_expr(Run):
	return DateFormat(Run.started_at, "%Y-%m")


def _in_period(Run, from_d, to_d):
	"""started_at inside [from_d, to_d], compared raw so the column index applies."""
	return (Run.started_at >= from_d) & (Run.started_at < getdate(add_days(to_d, 1)))


def _departments_for(users: list) -> dict:
	"""Map user -> Employee.department for the given users (one bulk query)."""
	users = [u for u in set(users) if u]
	if not users:
		return {}
	rows = frappe.get_all(
		"Employee",
		filters={"user_id": ["in", users]},
		fields=["user_id", "department"],
	)
	return {r["user_id"]: r["department"] for r in rows if r.get("department")}


def _department_labels(names: set) -> dict:
	"""Map Department name -> department_name, the name without the company suffix."""
	if not names:
		return {}
	rows = frappe.db.get_values("Department", {"name": ["in", list(names)]}, ["name", "department_name"], as_dict=True)
	return {r["name"]: r["department_name"] for r in rows}


def allocation_rows(axis: str, from_d, to_d, filters: list) -> list:
	"""Monthly usage rows at the titled grain the export's Detail sheet lists."""
	Run = DocType("AI Agent Run")
	Inst = DocType("BPMN Process Instance")
	month = _month_expr(Run)
	in_range = _in_period(Run, from_d, to_d)

	if axis == "chat_user":
		Conv = DocType("Chat Conversation")
		# LEFT join on context_docname so runs of a deleted conversation stay on this axis.
		q = (
			frappe.qb.from_(Run)
			.inner_join(Inst).on(Inst.name == Run.instance)
			.left_join(Conv).on(Conv.name == Inst.context_docname)
			.select(
				month.as_("month"),
				Conv.owner.as_("person"),
				Inst.context_docname.as_("subject"),
				Conv.title.as_("subject_label"),
				fn.Count("*").as_("runs"),
				fn.Sum(Run.total_tokens).as_("tokens"),
				fn.Sum(Run.estimated_cost).as_("cost"),
			)
			.where(in_range)
			.where(Inst.context_doctype == "Chat Conversation")
			.groupby(month, Conv.owner, Inst.context_docname, Conv.title)
		)
	else:
		Model = DocType("BPMN Process Model")
		Proc = DocType("Process")
		# A run with no process model has nothing to bill to, so it stays unallocated.
		q = (
			frappe.qb.from_(Run)
			.left_join(Inst).on(Inst.name == Run.instance)
			.left_join(Model).on(Model.name == Run.process_model)
			.left_join(Proc).on(Proc.name == Model.process_name)
			.select(
				month.as_("month"),
				Proc.process_owner.as_("person"),
				Run.process_model.as_("subject"),
				Model.process_name.as_("subject_label"),
				fn.Count("*").as_("runs"),
				fn.Sum(Run.total_tokens).as_("tokens"),
				fn.Sum(Run.estimated_cost).as_("cost"),
			)
			.where(in_range)
			.where(Inst.context_doctype.isnull() | (Inst.context_doctype != "Chat Conversation"))
			.where(Run.process_model.isnotnull())
			.where(Run.process_model != "")
			.groupby(month, Proc.process_owner, Run.process_model, Model.process_name)
		)

	raw = apply_conditions(q, filters).run(as_dict=True)
	departments = _departments_for([r.get("person") for r in raw])
	rows = []
	for r in raw:
		person = cstr(r.get("person"))
		rows.append({
			"month": cstr(r.get("month")),
			"person": person,
			"department": departments.get(person) or "",
			"subject": cstr(r.get("subject")),
			"subject_label": cstr(r.get("subject_label")) or cstr(r.get("subject")),
			"runs": cint(r.get("runs")),
			"tokens": cint(r.get("tokens")),
			"cost": flt(r.get("cost"), 6),
		})
	rows.sort(key=lambda x: (x["month"], x["department"], x["person"], x["subject_label"]), reverse=False)
	return rows


def sum_period_totals(from_d, to_d, filters: list) -> dict:
	"""The period's totals across both axes under the header filters; each axis covers only its slice."""
	Run = DocType("AI Agent Run")
	q = (
		frappe.qb.from_(Run)
		.select(
			fn.Count("*").as_("runs"),
			fn.Sum(Run.total_tokens).as_("tokens"),
			fn.Sum(Run.estimated_cost).as_("cost"),
		)
		.where(_in_period(Run, from_d, to_d))
	)
	row = apply_conditions(q, filters).run(as_dict=True)
	r = row[0] if row else {}
	return {
		"runs": cint(r.get("runs")),
		"tokens": cint(r.get("tokens")),
		"cost": flt(r.get("cost"), 6),
	}


def find_models_missing_pricing(from_d, to_d, filters: list) -> list:
	"""Models used in the period that have no rate card on their AI Model, so
	their spend silently counts as 0; finance needs to know."""
	from one_bpmn.ai_agent_observability.pricing import get_model_pricing

	Run = DocType("AI Agent Run")
	q = (
		frappe.qb.from_(Run)
		.select(Run.model)
		.distinct()
		.where(_in_period(Run, from_d, to_d))
		.where(Run.model.isnotnull())
		.where(Run.model != "")
	)
	used = apply_conditions(q, filters).run(as_dict=True)
	return sorted({r["model"] for r in used if not get_model_pricing(r["model"])})


def sum_other_axis_cost(axis: str, from_d, to_d, filters: list) -> float:
	"""The cost the other axis allocates for the same period and filters."""
	Run = DocType("AI Agent Run")
	Inst = DocType("BPMN Process Instance")
	q = (
		frappe.qb.from_(Run)
		.left_join(Inst).on(Inst.name == Run.instance)
		.select(fn.Sum(Run.estimated_cost).as_("cost"))
		.where(_in_period(Run, from_d, to_d))
	)
	if axis == "chat_user":
		# The process axis bills only runs that carry a process model.
		q = (
			q.where(Inst.context_doctype.isnull() | (Inst.context_doctype != "Chat Conversation"))
			.where(Run.process_model.isnotnull())
			.where(Run.process_model != "")
		)
	else:
		q = q.where(Inst.context_doctype == "Chat Conversation")
	row = apply_conditions(q, filters).run(as_dict=True)
	return flt(row[0].get("cost"), 6)


def allocation_leaves(axis: str, from_d, to_d, filters: list) -> list:
	"""One row per day, person and subject: the grain the tree, chart and totals fold."""
	Run = DocType("AI Agent Run")
	Inst = DocType("BPMN Process Instance")
	day = fn.Date(Run.started_at)
	in_range = _in_period(Run, from_d, to_d)

	if axis == "chat_user":
		Conv = DocType("Chat Conversation")
		User = DocType("User")
		q = (
			frappe.qb.from_(Run)
			.inner_join(Inst).on(Inst.name == Run.instance)
			.left_join(Conv).on(Conv.name == Inst.context_docname)
			.left_join(User).on(User.name == Conv.owner)
			.select(
				day.as_("day"),
				Conv.owner.as_("person"),
				User.full_name.as_("person_name"),
				Conv.agent_mode.as_("subject"),
				Inst.context_docname.as_("conversation"),
				fn.Count("*").as_("runs"),
				fn.Sum(Run.total_tokens).as_("tokens"),
				fn.Sum(Run.estimated_cost).as_("cost"),
			)
			.where(in_range)
			.where(Inst.context_doctype == "Chat Conversation")
			.groupby(day, Conv.owner, User.full_name, Conv.agent_mode, Inst.context_docname)
		)
	else:
		Model = DocType("BPMN Process Model")
		Proc = DocType("Process")
		q = (
			frappe.qb.from_(Run)
			.left_join(Inst).on(Inst.name == Run.instance)
			.left_join(Model).on(Model.name == Run.process_model)
			.left_join(Proc).on(Proc.name == Model.process_name)
			.select(
				day.as_("day"),
				Proc.process_owner.as_("person"),
				Proc.process_owner_name.as_("person_name"),
				Run.process_model.as_("subject"),
				Model.process_name.as_("subject_label"),
				fn.Count("*").as_("runs"),
				fn.Sum(Run.total_tokens).as_("tokens"),
				fn.Sum(Run.estimated_cost).as_("cost"),
			)
			.where(in_range)
			.where(Inst.context_doctype.isnull() | (Inst.context_doctype != "Chat Conversation"))
			.where(Run.process_model.isnotnull())
			.where(Run.process_model != "")
			.groupby(day, Proc.process_owner, Proc.process_owner_name, Run.process_model, Model.process_name)
		)

	raw = apply_conditions(q, filters).run(as_dict=True)
	departments = _departments_for([r.get("person") for r in raw])
	labels = _department_labels(set(departments.values()))
	leaves = []
	for r in raw:
		person = cstr(r.get("person"))
		department = departments.get(person) or ""
		subject = cstr(r.get("subject")) or (GENERAL_CHAT if axis == "chat_user" else "")
		leaves.append({
			"day": getdate(r.get("day")),
			"person": person,
			"person_name": cstr(r.get("person_name")),
			"department": department,
			"department_label": labels.get(department, department),
			"subject": subject,
			# Chat leaves are named by agent; conversation titles never reach the tree.
			"subject_label": cstr(r.get("subject_label")) or _(subject),
			"conversation": cstr(r.get("conversation")),
			"runs": cint(r.get("runs")),
			"tokens": cint(r.get("tokens")),
			"cost": flt(r.get("cost"), 6),
		})
	return leaves


def run_filters(origin: str, process_model: str = None) -> list:
	"""The header's origin and process filters as conditions every query in the report applies."""
	Run = DocType("AI Agent Run")
	conditions = [origin_condition(Run, origin)]
	if process_model:
		conditions.append(Run.process_model == process_model)
	return conditions
