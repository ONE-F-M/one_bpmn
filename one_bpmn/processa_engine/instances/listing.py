# Copyright (c) 2026, one-fm and contributors
"""Reads for the instance list and detail pages, and the DocTypes Processa runs."""

import json
import re

import frappe
from frappe import _

SEARCH_FIELDS = ("process_model", "name", "context_doctype", "context_docname", "initiated_by")

# Cache key for the doctype-level "is this run via Processa?" lookup.
PROCESSA_DOCTYPES_CACHE_KEY = "one_bpmn_processa_controlled_doctypes"


def list_process_instances(
	filters=None,
	limit_start=0,
	limit_page_length=20,
	order_by="creation desc",
	pending_action_by=None,
	search=None,
) -> list:
	"""BPMN process instances with their waiting tasks joined as current_step.
	search ranks results by match quality instead of order_by; pending_action_by keeps Active instances that user must act on."""

	if isinstance(filters, str):
		filters = json.loads(filters)

	if isinstance(limit_start, str):
		limit_start = int(limit_start)
	if isinstance(limit_page_length, str):
		limit_page_length = int(limit_page_length)

	if pending_action_by:
		pending = _instances_pending_on(pending_action_by)
		if not pending:
			return []
		# A Waiting row can outlive its instance, so pin to Active, the only actionable status.
		if isinstance(filters, list):
			filters = filters + [["name", "in", pending], ["status", "=", "Active"]]
		else:
			filters = dict(filters or {})
			filters["name"] = ["in", pending]
			filters["status"] = "Active"

	ranked_names = None
	if search and search.strip():
		ranked_names = _rank_instances(filters, search)[limit_start : limit_start + limit_page_length]
		if not ranked_names:
			return []
		if isinstance(filters, list):
			filters = filters + [["name", "in", ranked_names]]
		else:
			filters = {**(filters or {}), "name": ["in", ranked_names]}
		limit_start = 0

	instances = frappe.get_list(
		"BPMN Process Instance",
		fields=[
			"name",
			"process_model",
			"status",
			"waiting_for_ai",
			"context_doctype",
			"context_docname",
			"started_at",
			"initiated_by",
		],
		filters=filters,
		limit_start=limit_start,
		limit_page_length=limit_page_length,
		order_by=order_by,
	)

	if ranked_names:
		instances.sort(key=lambda d: ranked_names.index(d.name))

	if instances:
		instance_names = [d.name for d in instances]
		tasks = frappe.get_all(
			"BPMN Active Task",
			filters={
				"parent": ["in", instance_names],
				"parenttype": "BPMN Process Instance",
				"status": ["in", ["Waiting", ""]],
			},
			fields=["parent", "task_name", "status"],
		)

		from collections import defaultdict

		task_map = defaultdict(list)
		for t in tasks:
			task_map[t.parent].append(t.task_name)

		for d in instances:
			d.current_step = ", ".join(task_map.get(d.name, []))

		# An Active instance with no waiting user task still has a position; derive it from the engine state.
		needs_derivation = [
			d.name for d in instances if d.status == "Active" and not d.current_step
		]
		if needs_derivation:
			states = frappe.get_all(
				"BPMN Process Instance",
				filters={"name": ["in", needs_derivation]},
				fields=["name", "workflow_state"],
			)
			derived = {row.name: _derive_current_step(row.workflow_state) for row in states}
			for d in instances:
				if not d.current_step:
					d.current_step = derived.get(d.name, "")

	return instances


def _words(text: str) -> list:
	return re.findall(r"[a-z0-9]+", (text or "").lower())


def _is_subsequence(needle: str, haystack: str) -> bool:
	chars = iter(haystack)
	return all(c in chars for c in needle)


def _search_rank(query: str, row: dict):
	"""Rank of a search match, lower is better, None for no match: 0 substring, 1 token prefixes, 2 initials."""
	query = (query or "").strip().lower()
	values = [str(row.get(f) or "") for f in SEARCH_FIELDS]
	text = " ".join(values).lower()
	if query in text:
		return 0

	compact = "".join(query.split())
	if len(compact) < 2:
		return None

	words = _words(text)
	tokens = _words(query)
	unused = list(words)
	for token in tokens:
		match = next((w for w in unused if w.startswith(token)), None)
		if match is None:
			break
		unused.remove(match)
	else:
		return 1

	for value in values:
		initials = "".join(w[0] + "".join(c for c in w[1:] if c.isdigit()) for w in _words(value))
		if _is_subsequence(compact, initials):
			return 2
	return None


def _rank_instances(filters, search: str) -> list:
	"""Names of the instances matching ``search`` under ``filters``, best match first."""
	rows = frappe.get_list(
		"BPMN Process Instance",
		fields=list(SEARCH_FIELDS),
		filters=filters,
		limit_page_length=0,
		order_by="creation desc",
	)
	scored = [(_search_rank(search, row), i, row.name) for i, row in enumerate(rows)]
	return [name for rank, _, name in sorted(r for r in scored if r[0] is not None)]


def _instances_pending_on(user: str) -> list:
	"""Names of process instances holding a Waiting task ``user`` must act on, by the rule complete_task applies.
	A task reaches a user through assigned_user (a comma-joined list, so the LIKE only pre-filters) or,
	while no user is resolved onto the row, through assigned_role."""
	# Imported lazily: assignment.py pulls in engine.py, which is fragile across SpiffWorkflow versions.
	from one_bpmn.processa_engine.assignment import task_actors

	roles = frappe.get_roles(user)

	or_filters = [
		["BPMN Active Task", field, "like", f"%{name}%"]
		for name in {user, *_users_covered_by(user)}
		for field in ("assigned_user", "relieved_user", "reliever_user")
	]
	if roles:
		or_filters.append(["BPMN Active Task", "assigned_role", "in", roles])

	rows = frappe.get_all(
		"BPMN Active Task",
		filters={"parenttype": "BPMN Process Instance", "status": "Waiting"},
		or_filters=or_filters,
		fields=["parent", "assigned_user", "relieved_user", "reliever_user", "assigned_role"],
	)

	role_set = set(roles)
	return list(
		{
			row.parent
			for row in rows
			if user in task_actors(row)
			or (not (row.assigned_user or "").strip() and row.assigned_role in role_set)
		}
	)


def _users_covered_by(user: str) -> list:
	"""User IDs of employees whose approved leave today names ``user`` as their reliever."""
	today = frappe.utils.today()
	employees = frappe.get_all(
		"Leave Application",
		filters={
			"status": "Approved",
			"reliever_user_id": user,
			"from_date": ["<=", today],
			"to_date": [">=", today],
		},
		pluck="employee",
	)
	if not employees:
		return []
	return frappe.get_all(
		"Employee",
		filters={"name": ["in", employees], "user_id": ["is", "set"]},
		pluck="user_id",
	)


def _derive_current_step(workflow_state: str) -> str:
	"""The engine's current position from serialized state: active non-internal tasks, descending into subprocesses.
	A container with no active inner task is reported as awaiting task selection (ad-hoc) or in progress, never blank."""
	try:
		state = json.loads(workflow_state or "{}")
	except Exception:
		return ""
	if not state:
		return ""

	ACTIVE_STATES = {8, 16, 32}  # WAITING, READY, STARTED
	subprocesses = state.get("subprocesses") or {}
	subprocess_specs = state.get("subprocess_specs") or {}

	def display(spec_map, spec_name):
		spec_data = (spec_map or {}).get(spec_name) or {}
		return spec_data.get("bpmn_name") or spec_data.get("description") or spec_name

	def active_tasks(tasks_dict):
		for task_id, t in (tasks_dict or {}).items():
			spec = t.get("task_spec") or ""
			if not spec or spec in ("Start", "End"):
				continue
			if spec.endswith(".EndJoin") or ".BoundaryEvent" in spec:
				continue
			if (t.get("state") or 0) in ACTIVE_STATES:
				yield task_id, spec

	def describe(tasks_dict, spec_map):
		labels = []
		for task_id, spec_name in active_tasks(tasks_dict):
			sub = subprocesses.get(task_id)
			if sub is None:
				labels.append(display(spec_map, spec_name))
				continue
			child_specs = (subprocess_specs.get(spec_name) or {}).get("task_specs") or {}
			inner = describe(sub.get("tasks"), child_specs)
			if inner:
				labels.append(inner)
			else:
				typename = ((spec_map or {}).get(spec_name) or {}).get("typename") or ""
				label = display(spec_map, spec_name)
				if "AdHoc" in typename:
					labels.append(f"{label} - awaiting task selection")
				else:
					labels.append(f"{label} - in progress")
		return ", ".join(labels)

	top_specs = (state.get("spec") or {}).get("task_specs") or {}
	return describe(state.get("tasks"), top_specs)


def get_instance_tasks(instance_name: str) -> dict:
	"""The status and current active tasks of a process instance."""
	if not instance_name:
		frappe.throw(_("instance_name is required"))

	instance = frappe.get_doc("BPMN Process Instance", instance_name)
	instance.check_permission("read")

	return {
		"instance": instance_name,
		"status": instance.status,
		"process_model": instance.process_model,
		"context_doctype": instance.context_doctype,
		"context_docname": instance.context_docname,
		"initiated_by": instance.initiated_by,
		"started_at": str(instance.started_at) if instance.started_at else None,
		"completed_at": str(instance.completed_at) if instance.completed_at else None,
		"active_tasks": instance.get_active_tasks_summary(),
	}


def get_processa_controlled_doctypes() -> list:
	"""DocTypes an active BPMN Process Model starts on (DocType Event start trigger) or targets (BPMN Process DocType).
	bpmn_form_actions.js hides the native controls Processa owns on them; cached until clear_processa_doctype_cache."""
	cached = frappe.cache().get_value(PROCESSA_DOCTYPES_CACHE_KEY)
	if cached is not None:
		return cached

	rows = frappe.get_all(
		"BPMN Start Event Config",
		filters={"trigger_type": "DocType Event", "parenttype": "BPMN Process Model"},
		fields=["parent", "trigger_doctype as doctype_name"],
	)
	rows += frappe.get_all(
		"BPMN Process DocType",
		filters={"parenttype": "BPMN Process Model"},
		fields=["parent", "doctype_name"],
	)
	rows = [r for r in rows if r.doctype_name and r.parent]

	doctypes = []
	if rows:
		active_models = set(
			frappe.get_all(
				"BPMN Process Model",
				filters={"name": ["in", list({r.parent for r in rows})], "is_active": 1},
				pluck="name",
			)
		)
		doctypes = sorted({r.doctype_name for r in rows if r.parent in active_models})

	frappe.cache().set_value(PROCESSA_DOCTYPES_CACHE_KEY, doctypes)
	return doctypes


def clear_processa_doctype_cache(doc=None, method=None):
	"""Drop the cached Processa-controlled DocType list (doc_events hook)."""
	frappe.cache().delete_value(PROCESSA_DOCTYPES_CACHE_KEY)
