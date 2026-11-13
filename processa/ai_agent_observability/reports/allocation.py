"""Cost allocation report: tree, totals and export."""
from __future__ import annotations

import base64
from collections import defaultdict

import frappe
from frappe import _
from frappe.query_builder import DocType
from frappe.query_builder import functions as fn
from frappe.utils import add_days, add_months, cint, cstr, flt, get_last_day, getdate

from processa.ai_agent_observability.reports.allocation_data import (
	allocation_leaves,
	allocation_rows,
	find_models_missing_pricing,
	run_filters,
	sum_other_axis_cost,
	sum_period_totals,
)
from processa.ai_agent_observability.reports.periods import bucket_start, default_dates, previous_period


# ---------------------------------------------------------------------------
# 6. Cost allocation
# ---------------------------------------------------------------------------
# A run whose BPMN instance context is a Chat Conversation bills its user; every other run bills its process owner.

ALLOCATION_AXES = ("process_owner", "chat_user")

ALLOCATION_ORIGINS = ("production", "eval", "all")

# Top level of a tree per grouping, then the levels under it; department is never a child.
ALLOCATION_LEVELS = {
	("process_owner", "department"): ("department", "owner", "process"),
	("process_owner", "owner"): ("owner", "process"),
	("process_owner", "process"): ("process", "owner"),
	("chat_user", "department"): ("department", "user", "agent"),
	("chat_user", "user"): ("user", "agent"),
	("chat_user", "agent"): ("agent", "user"),
}

DEFAULT_GROUP_BY = "department"

# Chat users listed under a parent before the rest fold into one "more" node.
MAX_PEER_NODES = 5

# Holders of this role are the chat seats; without it, active employees with a login are.
CHAT_SEAT_ROLE = "Chat User"


def _allocation_previous_period(from_d, to_d) -> tuple:
	"""The same days a span of whole months back when the range starts on the 1st,
	else the window of equal length ending the day before."""
	if from_d.day == 1:
		months = (to_d.year - from_d.year) * 12 + to_d.month - from_d.month + 1
		prev_from = getdate(add_months(from_d, -months))
		prev_to = getdate(add_months(to_d, -months))
		if to_d == getdate(get_last_day(to_d)):
			prev_to = getdate(get_last_day(prev_to))
		return prev_from, prev_to
	return previous_period(from_d, to_d)


def _allocation_bucket_start(day, grain: str, from_d):
	"""The chart bucket a day belongs to, clipped to the start of the range."""
	return max(bucket_start(day, grain), from_d)


def _period_grain(from_d, to_d) -> tuple:
	"""(grain, buckets, months) for the range: weeks inside one calendar month,
	months once it spans more than one."""
	days = [getdate(add_days(from_d, i)) for i in range((to_d - from_d).days + 1)]
	months = sorted({d.strftime("%Y-%m") for d in days})
	grain = "week" if len(months) == 1 else "month"
	buckets = list(dict.fromkeys(cstr(_allocation_bucket_start(d, grain, from_d)) for d in days))
	return grain, buckets, months


def _level_of(level: str, leaf: dict) -> tuple:
	"""(key, label) a leaf contributes at one level of the tree."""
	if level == "department":
		return leaf["department"], leaf["department_label"] or _("Unassigned")
	if level in ("owner", "user"):
		return leaf["person"], leaf["person"] or _("unassigned")
	return leaf["subject"], leaf["subject_label"]


def _fold(leaves: list, levels: tuple, buckets: list, months: list, grain: str, from_d) -> dict:
	"""Aggregate leaves into {path -> metrics} for every node and every prefix,
	so a parent's numbers are its children's by construction."""
	agg = {}
	for leaf in leaves:
		bucket = cstr(_allocation_bucket_start(leaf["day"], grain, from_d))
		month = leaf["day"].strftime("%Y-%m")
		path = ()
		for level in levels:
			key, label = _level_of(level, leaf)
			path = (*path, key)
			node = agg.get(path)
			if node is None:
				node = agg[path] = {
					"kind": level,
					"key": key,
					"label": label,
					"name": leaf["person_name"] if level in ("owner", "user") else "",
					"department": leaf["department"],
					"runs": 0,
					"tokens": 0,
					"cost": 0.0,
					"by_bucket": {b: 0.0 for b in buckets},
					"by_month": {m: 0.0 for m in months},
					"people": set(),
					"subjects": set(),
					"conversations": set(),
				}
			node["runs"] += leaf["runs"]
			node["tokens"] += leaf["tokens"]
			node["cost"] += leaf["cost"]
			node["by_bucket"][bucket] = node["by_bucket"].get(bucket, 0.0) + leaf["cost"]
			node["by_month"][month] = node["by_month"].get(month, 0.0) + leaf["cost"]
			if leaf["person"]:
				node["people"].add(leaf["person"])
			if leaf["subject"]:
				node["subjects"].add(leaf["subject"])
			if leaf["conversation"]:
				node["conversations"].add(leaf["conversation"])
	return agg


def _share(cost: float, total: float) -> float:
	return flt(cost / total * 100, 2) if total else 0.0


def _delta(cost: float, previous: float):
	"""Change against the prior period in percent, or None when there is nothing to compare against."""
	return flt((cost - previous) / previous * 100, 1) if previous else None


def _allocation_tree(agg: dict, previous: dict, total_cost: float, axis: str) -> list:
	"""Nest the folded paths, heaviest first at every level."""
	children = defaultdict(list)
	for path in agg:
		children[path[:-1]].append(path)

	def nodes_of(parent: tuple) -> list:
		paths = sorted(children.get(parent, ()), key=lambda p: (-agg[p]["cost"], agg[p]["label"]))
		out = [node_of(p) for p in paths]
		too_many_users = len(out) > MAX_PEER_NODES and out[0]["kind"] == "user"
		if parent and too_many_users:
			out, rest = out[:MAX_PEER_NODES], out[MAX_PEER_NODES:]
			out.append(_more_node(rest, total_cost))
		return out

	def node_of(path: tuple) -> dict:
		a = agg[path]
		cost = flt(a["cost"], 6)
		previous_cost = flt(previous.get(path, 0.0), 6)
		node = {
			"kind": a["kind"],
			"key": a["key"],
			"label": a["label"],
			"name": a["name"],
			"department": a["department"],
			"runs": a["runs"],
			"tokens": a["tokens"],
			"cost": cost,
			"share": _share(cost, total_cost),
			"previous_cost": previous_cost,
			"delta": _delta(cost, previous_cost),
			"by_bucket": {k: flt(v, 6) for k, v in a["by_bucket"].items()},
			"by_month": {k: flt(v, 6) for k, v in a["by_month"].items()},
			"children": nodes_of(path),
		}
		if axis == "chat_user":
			conversations = len(a["conversations"])
			node["users"] = len(a["people"])
			node["agents"] = len(a["subjects"])
			node["conversations"] = conversations
			node["avg_cost_per_conversation"] = flt(cost / conversations, 6) if conversations else 0.0
		else:
			node["owners"] = len(a["people"])
			node["processes"] = len(a["subjects"])
		return node

	return nodes_of(())


def _more_node(rest: list, total_cost: float) -> dict:
	"""The tail of a long peer list, as one row that still carries its money."""
	cost = flt(sum(n["cost"] for n in rest), 6)
	previous_cost = flt(sum(n["previous_cost"] for n in rest), 6)
	node = {
		"kind": "more",
		"key": "",
		"label": _("{0} more").format(len(rest)),
		"count": len(rest),
		"department": "",
		"runs": sum(n["runs"] for n in rest),
		"tokens": sum(n["tokens"] for n in rest),
		"cost": cost,
		"share": _share(cost, total_cost),
		"previous_cost": previous_cost,
		"delta": _delta(cost, previous_cost),
		"by_bucket": _sum_series(rest, "by_bucket"),
		"by_month": _sum_series(rest, "by_month"),
		"children": [],
	}
	node["conversations"] = sum(n["conversations"] for n in rest)
	return node


def _sum_series(nodes: list, key: str) -> dict:
	out = {}
	for node in nodes:
		for bucket, cost in node[key].items():
			out[bucket] = flt(out.get(bucket, 0.0) + cost, 6)
	return out


def _chat_seats() -> int:
	"""Enabled users holding the chat role, or enabled users of active employees without it."""
	User = DocType("User")
	q = frappe.qb.from_(User).select(fn.Count(User.name).distinct()).where(User.enabled == 1)
	if frappe.db.exists("Role", CHAT_SEAT_ROLE):
		HasRole = DocType("Has Role")
		q = q.inner_join(HasRole).on(
			(HasRole.parent == User.name) & (HasRole.parenttype == "User") & (HasRole.role == CHAT_SEAT_ROLE)
		)
	else:
		Employee = DocType("Employee")
		q = q.inner_join(Employee).on((Employee.user_id == User.name) & (Employee.status == "Active"))
	return cint(q.run()[0][0])


def _window_figures(leaves: list) -> dict:
	"""Spend, volume and audience of one window's leaves, with the averages the tiles compare."""
	cost = flt(sum(x["cost"] for x in leaves), 6)
	runs = sum(x["runs"] for x in leaves)
	users = len({x["person"] for x in leaves if x["person"]})
	conversations = len({x["conversation"] for x in leaves if x["conversation"]})
	return {
		"runs": runs,
		"tokens": sum(x["tokens"] for x in leaves),
		"cost": cost,
		"users": users,
		"conversations": conversations,
		"avg_cost_per_run": flt(cost / runs, 6) if runs else 0.0,
		"avg_cost_per_user": flt(cost / users, 6) if users else 0.0,
		"avg_cost_per_conversation": flt(cost / conversations, 6) if conversations else 0.0,
	}


def _allocation_totals(axis: str, leaves: list, from_d, to_d, filters: list) -> dict:
	"""The tile numbers for this axis: its own spend, never the period's."""
	now = _window_figures(leaves)
	cost = now["cost"]
	totals = {
		"runs": now["runs"],
		"tokens": now["tokens"],
		"cost": cost,
		"people": now["users"],
		"departments": len({x["department"] for x in leaves if x["department"]}),
		"avg_cost_per_run": now["avg_cost_per_run"],
		"other_axis_cost": sum_other_axis_cost(axis, from_d, to_d, filters),
	}

	if axis == "chat_user":
		by_user = defaultdict(float)
		by_department = defaultdict(float)
		for leaf in leaves:
			# Spend with no department to bill stays in the tree but never tops the tile.
			if leaf["department"]:
				by_department[leaf["department_label"]] += leaf["cost"]
			if leaf["person"]:
				by_user[leaf["person"]] += leaf["cost"]
		top5 = sorted(by_user.values(), reverse=True)[:MAX_PEER_NODES]
		top_department = max(by_department.items(), key=lambda kv: kv[1]) if by_department else ("", 0.0)
		totals.update({
			"active_users": now["users"],
			"seats": _chat_seats(),
			"conversations": now["conversations"],
			"avg_cost_per_user": now["avg_cost_per_user"],
			"avg_cost_per_conversation": now["avg_cost_per_conversation"],
			"top5_share": _share(flt(sum(top5), 6), cost),
			"top_department": {
				"name": top_department[0] or _("Unassigned"),
				"share": _share(flt(top_department[1], 6), cost),
			},
		})
	else:
		subjects = _subjects_by_cost(leaves, cost)
		totals.update({
			"processes": len(subjects),
			"top_process": subjects[0]["label"] if subjects else "",
		})
	return totals


def _subjects_by_cost(leaves: list, total_cost: float) -> list:
	"""Spend per process (non-chat) or per agent (chat), heaviest first."""
	by_subject = defaultdict(lambda: {"cost": 0.0, "runs": 0, "label": ""})
	for leaf in leaves:
		entry = by_subject[leaf["subject"]]
		entry["cost"] += leaf["cost"]
		entry["runs"] += leaf["runs"]
		entry["label"] = leaf["subject_label"]
	return [
		{
			"key": key,
			"label": entry["label"],
			"runs": entry["runs"],
			"cost": flt(entry["cost"], 6),
			"share": _share(flt(entry["cost"], 6), total_cost),
		}
		for key, entry in sorted(by_subject.items(), key=lambda kv: -kv[1]["cost"])
	]


def get_cost_allocation(
	from_date: str = None,
	to_date: str = None,
	axis: str = "process_owner",
	group_by: str = None,
	origin: str = "production",
	process_model: str = None,
) -> dict:
	"""AI spend allocated by Process Owner (non-chat) or chat user, as a department
	tree with each node's share, prior-period cost and cost per chart bucket."""
	if axis not in ALLOCATION_AXES:
		frappe.throw(_("axis must be one of {0}").format(", ".join(ALLOCATION_AXES)))
	if origin not in ALLOCATION_ORIGINS:
		frappe.throw(_("origin must be one of {0}").format(", ".join(ALLOCATION_ORIGINS)))
	group_by = group_by or DEFAULT_GROUP_BY
	if (axis, group_by) not in ALLOCATION_LEVELS:
		options = ", ".join(g for (a, g) in ALLOCATION_LEVELS if a == axis)
		frappe.throw(_("group_by must be one of {0}").format(options))
	from_d, to_d = default_dates(from_date, to_date, days=30)
	if from_d > to_d:
		frappe.throw(_("From date must be on or before to date"))

	levels = ALLOCATION_LEVELS[(axis, group_by)]
	grain, buckets, months = _period_grain(from_d, to_d)
	prev_from, prev_to = _allocation_previous_period(from_d, to_d)
	filters = run_filters(origin, process_model)

	leaves = allocation_leaves(axis, from_d, to_d, filters)
	prev_leaves = allocation_leaves(axis, prev_from, prev_to, filters)
	totals = _allocation_totals(axis, leaves, from_d, to_d, filters)
	previous = {
		path: node["cost"]
		for path, node in _fold(prev_leaves, levels, [], [], grain, prev_from).items()
	}
	tree = _allocation_tree(
		_fold(leaves, levels, buckets, months, grain, from_d), previous, totals["cost"], axis
	)

	return {
		"axis": axis,
		"group_by": group_by,
		"origin": origin,
		"from_date": cstr(from_d),
		"to_date": cstr(to_d),
		"grain": grain,
		"buckets": buckets,
		"months": months,
		"tree": tree,
		# The chat donut is by agent; the process axis reads its shares off the tree.
		"agents": _subjects_by_cost(leaves, totals["cost"]) if axis == "chat_user" else [],
		"previous": {"from_date": cstr(prev_from), "to_date": cstr(prev_to), **_window_figures(prev_leaves)},
		# This axis only; period_totals covers both.
		"totals": totals,
		"period_totals": sum_period_totals(from_d, to_d, filters),
		"models_missing_pricing": find_models_missing_pricing(from_d, to_d, filters),
	}


def _summary_sheet(report: dict) -> list:
	"""One row per tree node, depth first, with month columns while there are two to six."""
	axis = report["axis"]
	months = report["months"] if 2 <= len(report["months"]) <= 6 else []
	person_header = _("User") if axis == "chat_user" else _("Owner")
	subject_header = _("Agent") if axis == "chat_user" else _("Process")
	data = [[
		_("Level"), _("Name"), _("Department"), _("Runs"), _("Tokens"), _("Cost"),
		_("Share %"), _("Previous Cost"), _("Change %"),
		*months,
	]]

	kinds = {
		"owner": person_header,
		"user": person_header,
		"process": subject_header,
		"agent": subject_header,
		"department": _("Department"),
		"more": _("Other"),
	}

	def walk(nodes):
		for node in nodes:
			data.append([
				kinds[node["kind"]],
				node["label"],
				node["department"],
				node["runs"],
				node["tokens"],
				flt(node["cost"], 6),
				node["share"],
				node["previous_cost"],
				"" if node["delta"] is None else node["delta"],
				*(flt(node["by_month"][m], 6) for m in months),
			])
			walk(node["children"])

	walk(report["tree"])
	totals = report["totals"]
	delta = _delta(totals["cost"], report["previous"]["cost"])
	data.append([
		_("Total"), "", "", totals["runs"], totals["tokens"], flt(totals["cost"], 6),
		100.0 if totals["cost"] else 0.0, report["previous"]["cost"],
		"" if delta is None else delta,
		*([""] * len(months)),
	])
	return data


def _detail_sheet(axis: str, rows: list) -> list:
	subject_header = _("Chat") if axis == "chat_user" else _("Process")
	person_header = _("User") if axis == "chat_user" else _("Process Owner")
	data = [[_("Month"), _("Department"), person_header, subject_header,
			 _("Runs"), _("Tokens"), _("Cost")]]
	for r in rows:
		data.append([
			r["month"], r["department"], r["person"], r["subject_label"],
			r["runs"], r["tokens"], flt(r["cost"], 6),
		])
	return data


def export_cost_allocation(
	from_date: str = None,
	to_date: str = None,
	axis: str = "process_owner",
	group_by: str = None,
	origin: str = "production",
	process_model: str = None,
	fmt: str = "xlsx",
) -> dict:
	"""The cost allocation as an XLSX or CSV file, base64 encoded, with its filename."""
	if fmt not in ("xlsx", "csv"):
		frappe.throw(_("fmt must be 'xlsx' or 'csv'"))
	report = get_cost_allocation(from_date, to_date, axis, group_by, origin, process_model)
	# Conversation titles appear only here, in the Detail sheet.
	filters = run_filters(origin, process_model)
	rows = allocation_rows(axis, getdate(report["from_date"]), getdate(report["to_date"]), filters)

	stem = f"cost-allocation-{report['axis']}-{report['from_date']}-to-{report['to_date']}"
	if fmt == "xlsx":
		import openpyxl
		from frappe.utils.xlsxutils import make_xlsx

		# make_xlsx inserts each sheet first and saves every call, so it needs a normal workbook.
		wb = openpyxl.Workbook()
		wb.remove(wb.active)
		make_xlsx(_detail_sheet(axis, rows), "Detail", wb=wb)
		content = make_xlsx(_summary_sheet(report), "Summary", wb=wb).getvalue()
		filename = f"{stem}.xlsx"
	else:
		import csv
		import io

		buf = io.StringIO()
		csv.writer(buf).writerows(_summary_sheet(report))
		content = buf.getvalue().encode("utf-8-sig")  # BOM so Excel reads UTF-8
		filename = f"{stem}.csv"

	return {"filename": filename, "content": base64.b64encode(content).decode()}
