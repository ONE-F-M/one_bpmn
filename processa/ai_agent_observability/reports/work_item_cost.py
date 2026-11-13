"""Cost of the delegation chain behind one work item."""
from __future__ import annotations

import frappe
from frappe.query_builder import DocType
from frappe.utils import cint, flt

from processa.ai_agent_observability.reports.runs import TREE_MAX_DEPTH


# ---------------------------------------------------------------------------
# 7. Work item delegation cost
# ---------------------------------------------------------------------------
#
# A Work Item can be worked by an Orchestrator that delegates part of the
# job to specialists over A2A: the caller's BPMN Process Instance parks on
# an A2A Task, whose `instance` is the specialist's own process instance.
# A specialist can itself delegate further, so the chain must be walked, not
# just read one level deep — the same shape get_run_tree walks for a single
# run's tool-started children, just following A2A Task rows instead of
# parent_run.

def _instances_for_work_item(work_item_name: str) -> list:
	"""BPMN Process Instance names whose context is the given Work Item."""
	return frappe.get_all(
		"BPMN Process Instance",
		filters={"context_doctype": "Work Item", "context_docname": work_item_name},
		pluck="name",
	)


def _delegated_instances(caller_instances: list) -> list:
	"""The specialist instances these instances handed work to over A2A."""
	if not caller_instances:
		return []
	return [
		t.instance
		for t in frappe.get_all(
			"A2A Task",
			filters={"caller_instance": ["in", caller_instances], "instance": ["is", "set"]},
			fields=["instance"],
			limit_page_length=0,
		)
		if t.instance
	]


def _delegation_chain_instances(root_instances: list) -> tuple[list, bool]:
	"""Every instance in the delegation chain starting from *root_instances*,
	following A2A Task rows from caller_instance (the instance that parked,
	waiting) to instance (the specialist instance doing the delegated work),
	repeatedly — so a specialist that itself delegates further is caught too.

	Depth is capped at TREE_MAX_DEPTH, the same guard get_run_tree uses for
	its own recursion, so a bad or cyclic chain cannot loop forever.

	Returns the instances found and whether the cap stopped the walk with more
	chain still ahead. That second value matters here in a way it does not for
	get_run_tree: this walk feeds a cost total, and a total short by a level is
	an undercount that looks exactly like a correct answer.
	"""
	all_instances = list(dict.fromkeys(root_instances))
	frontier = list(root_instances)
	for _level in range(TREE_MAX_DEPTH):
		if not frontier:
			break
		next_frontier = []
		for instance in _delegated_instances(frontier):
			if instance not in all_instances:
				all_instances.append(instance)
				next_frontier.append(instance)
		frontier = next_frontier
	# A leftover frontier only says those instances went unexpanded, not that
	# any chain continues past them — asking is what stops a complete total
	# from being flagged as short.
	truncated = any(i not in all_instances for i in _delegated_instances(frontier))
	return all_instances, truncated


def search_orchestrator_work_items(query: str | None = None) -> list:
	"""Orchestrator Work Items whose name or title matches query, newest first, for the Work Items tab picker."""
	# Only Orchestrator work items reach an agent; any other would report a cost of zero.
	or_filters = [["name", "like", f"%{query}%"], ["title", "like", f"%{query}%"]] if query else None
	return frappe.get_list(
		"Work Item",
		fields=["name", "title"],
		filters={"orchestrator": 1},
		or_filters=or_filters,
		order_by="modified desc",
		limit_page_length=20,
	)


def get_work_item_delegation_cost(work_item_name: str) -> dict:
	"""Total AI cost for a Work Item, summed across every AI Agent Run in its
	delegation chain — every Orchestrator pass plus every specialist it handed
	work to over A2A, down to TREE_MAX_DEPTH levels.

	Returns zero totals and an empty breakdown, not an error, for a work item
	with no BPMN Process Instance or no runs at all.

	chain_truncated says the depth cap was reached with chain still unwalked,
	so the totals are a floor rather than the whole figure. Read it before
	quoting the number: nothing else distinguishes a complete total from a
	short one.
	"""

	root_instances = _instances_for_work_item(work_item_name)
	if not root_instances:
		return {"total_cost": 0.0, "total_tokens": 0, "breakdown": [], "chain_truncated": False}

	instances, chain_truncated = _delegation_chain_instances(root_instances)

	Run = DocType("AI Agent Run")
	rows = (
		frappe.qb.from_(Run)
		.select(
			Run.name,
			Run.agent_configuration,
			Run.model,
			Run.estimated_cost,
			Run.total_tokens,
		)
		.where(Run.instance.isin(instances))
		.orderby(Run.started_at)
		.run(as_dict=True)
	)

	breakdown = []
	total_cost = 0.0
	total_tokens = 0
	for r in rows:
		cost = flt(r.get("estimated_cost"), 6)
		tokens = cint(r.get("total_tokens"))
		total_cost += cost
		total_tokens += tokens
		breakdown.append({
			"run": r.get("name"),
			"agent_configuration": r.get("agent_configuration"),
			"model": r.get("model"),
			"cost": cost,
			"tokens": tokens,
		})

	return {
		"total_cost": flt(total_cost, 6),
		"total_tokens": total_tokens,
		"breakdown": breakdown,
		"chain_truncated": chain_truncated,
	}
