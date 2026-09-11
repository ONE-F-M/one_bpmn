"""
Tell the platform team when AI Memory outgrows exact semantic ranking.

Semantic memory search ranks the scope-filtered candidate set with an exact
cosine scan and no vector index. That decision was taken on measured evidence
and is bounded: past roughly 10,000 rows in one scope key, or 500,000 rows in
total, the scan cost stops being negligible and the design should be
reconsidered (the next step is a VECTOR INDEX inside the same MariaDB query).
Nothing else watches those bounds. This module does, once a day.

The thresholds live on Processa Settings; the constants in
``agents.memory.tools`` are only the defaults when the settings are blank.
"""

from __future__ import annotations

import frappe
from frappe import _

from one_bpmn.agents.memory.tools import REVISIT_SCOPE_ROWS, REVISIT_TOTAL_ROWS
from one_bpmn.agents.model_health import _dedupe, _is_real_user, _send_email, configured_recipients

# The scope key is polymorphic: which columns identify one key depends on the
# scope, so the count groups on all of them at once.
_SCOPE_KEY_COLUMNS = ("memory_scope", "agent_element", "process_model", "reference_doctype", "reference_name")


def _limit(fieldname: str, default: int) -> int:
	"""One threshold, with the code default standing in for one nobody has set.

	Blank, missing and 0 all mean "not set" here. Unlike the pruning rules, 0 is
	not an off switch for an alert: a threshold of 0 is crossed by the first
	memory ever written, so it would fire on every site every night. A field
	added to an existing Single reads back as 0 until somebody chooses a value,
	which is exactly the state that would produce that.
	"""
	try:
		value = frappe.db.get_single_value("Processa Settings", fieldname)
	except Exception:
		return default
	if value in (None, ""):
		return default
	return int(value) or default


def thresholds() -> tuple[int, int]:
	"""(per scope key, total). Processa Settings first, code defaults otherwise."""
	return (
		_limit("memory_scope_row_alert", REVISIT_SCOPE_ROWS),
		_limit("memory_total_row_alert", REVISIT_TOTAL_ROWS),
	)


def measure() -> dict:
	"""Row counts that matter: the table total and the largest scope key."""
	total = frappe.db.count("AI Memory")
	cols = ", ".join(f"`{c}`" for c in _SCOPE_KEY_COLUMNS)
	rows = frappe.db.sql(
		f"SELECT {cols}, COUNT(*) AS n FROM `tabAI Memory` GROUP BY {cols} ORDER BY n DESC LIMIT 1",
		as_dict=True,
	)
	largest = rows[0] if rows else None
	return {"total": total, "largest": largest}


def crossed(counts: dict, scope_limit: int, total_limit: int) -> list[str]:
	"""Human-readable line per threshold crossed. Pure function."""
	lines = []
	largest = counts.get("largest")
	if largest and largest["n"] > scope_limit:
		key = ", ".join(f"{c}={largest[c]}" for c in _SCOPE_KEY_COLUMNS if largest.get(c))
		lines.append(_("One scope key holds {0} memories (limit {1}): {2}").format(largest["n"], scope_limit, key))
	if counts.get("total", 0) > total_limit:
		lines.append(_("AI Memory holds {0} rows in total (limit {1})").format(counts["total"], total_limit))
	return lines


def check_volume() -> list[str]:
	"""Daily job. Alerts when a threshold is crossed; returns the lines sent."""
	scope_limit, total_limit = thresholds()
	lines = crossed(measure(), scope_limit, total_limit)
	if lines:
		_notify(lines)
	return lines


def _recipients() -> list[str]:
	users = _dedupe(configured_recipients())
	if users:
		return users
	managers = frappe.get_all("Has Role", filters={"role": "System Manager", "parenttype": "User"}, pluck="parent")
	return _dedupe(u for u in managers if _is_real_user(u))


def _notify(lines: list[str]) -> None:
	subject = _("AI Memory has outgrown exact semantic ranking")
	body = "<p>" + "</p><p>".join(lines) + "</p><p>" + _(
		"Memory search ranks candidates with an exact scan and no vector index, a decision made when the "
		"corpus was small. Review it now: the next step is a VECTOR INDEX inside the same MariaDB query. "
		"The thresholds live on Processa Settings, AI Memory section."
	) + "</p>"
	told = []
	for user in _recipients():
		try:
			note = frappe.new_doc("Notification Log")
			note.for_user = user
			note.type = "Alert"
			note.subject = subject
			note.email_content = body
			note.document_type = "Processa Settings"
			note.document_name = "Processa Settings"
			note.insert(ignore_permissions=True)
			told.append(user)
		except Exception:
			frappe.log_error(title="AI Memory volume: in-app alert failed", message=frappe.get_traceback())
	if told:
		try:
			_send_email(told, subject, body)
		except Exception:
			frappe.log_error(title="AI Memory volume: alert email failed", message=frappe.get_traceback())
