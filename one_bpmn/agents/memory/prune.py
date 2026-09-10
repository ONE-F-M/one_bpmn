"""
Nightly pruning of AI Memory beyond the per-row TTL.

``expires_on`` only removes what was given an expiry when written. Three more
kinds of memory decay into noise without one and used to stay forever:

- decayed: effective confidence (stored confidence, halving every 90 days
  since last written or corroborated) has fallen under the floor;
- never corroborated: nothing has restated it in a long time;
- irrelevant: a minor fact (importance 1) that has aged out.

Pruning is a soft delete: ``expires_on`` is set to now through ``doc.save`` so
the change lands as a Frappe Version, the row stays in the table for audit, and
``metadata.pruned`` records which rule fired and when. Nothing is hard-deleted.
A memory the user asked to be remembered (``user_directed``) is never pruned.

Every threshold lives on Processa Settings; 0 switches that rule off.
"""

from __future__ import annotations

import json

import frappe
from frappe.utils import cint, flt, get_datetime, now_datetime

from one_bpmn.agents.memory.tools import _json_loads, effective_confidence

# Rows invalidated per run at most, so one bad threshold cannot empty the store overnight.
SWEEP_LIMIT = 500
_PAGE = 1000

_DEFAULTS = {"min_confidence": 0.2, "uncorroborated_days": 180, "low_importance_days": 90}


def prune_config() -> dict:
	"""Thresholds from Processa Settings, code defaults when blank."""
	try:
		values = frappe.db.get_singles_dict("Processa Settings")
	except Exception:
		values = {}
	return {
		"min_confidence": flt(values.get("memory_prune_min_confidence"), 2) if values.get("memory_prune_min_confidence") is not None else _DEFAULTS["min_confidence"],
		"uncorroborated_days": cint(values.get("memory_prune_uncorroborated_days")) if values.get("memory_prune_uncorroborated_days") is not None else _DEFAULTS["uncorroborated_days"],
		"low_importance_days": cint(values.get("memory_prune_low_importance_days")) if values.get("memory_prune_low_importance_days") is not None else _DEFAULTS["low_importance_days"],
	}


def prune_reason(row: dict, config: dict, now=None) -> str | None:
	"""Which rule (if any) retires ``row``. Pure function; the tests drive it."""
	now = now or now_datetime()
	if row.get("user_directed"):
		return None
	age_days = (now - get_datetime(row.get("modified"))).total_seconds() / 86400.0 if row.get("modified") else 0.0
	never_corroborated = not cint(row.get("corroboration_count"))

	if config["min_confidence"] and effective_confidence(row, now) < config["min_confidence"]:
		return "decayed"
	if config["uncorroborated_days"] and never_corroborated and age_days > config["uncorroborated_days"]:
		return "never corroborated"
	if config["low_importance_days"] and never_corroborated and cint(row.get("importance")) <= 1 and age_days > config["low_importance_days"]:
		return "irrelevant"
	return None


def _invalidate(name: str, reason: str, now) -> None:
	doc = frappe.get_doc("AI Memory", name)
	metadata = _json_loads(doc.metadata) or {}
	metadata["pruned"] = {"reason": reason, "on": str(now)}
	doc.metadata = json.dumps(metadata)
	doc.expires_on = now
	# ignore_version=False so the retirement is captured as a Frappe Version even
	# under flags that would otherwise suppress it; history is the point.
	doc.save(ignore_permissions=True, ignore_version=False)


def prune_memories(limit: int = SWEEP_LIMIT) -> dict:
	"""Nightly sweep. Returns counts per reason plus ``scanned``."""
	config = prune_config()
	now = now_datetime()
	counts = {"decayed": 0, "never corroborated": 0, "irrelevant": 0, "scanned": 0}
	if not any(config.values()):
		return counts

	last_name = ""
	pruned = 0
	# ponytail: full scan of valid rows each night; add a modified-age prefilter when the table is large
	while pruned < limit:
		rows = frappe.db.sql(
			"""
			SELECT name, modified, confidence, corroboration_count, last_corroborated, importance, user_directed
			FROM `tabAI Memory`
			WHERE name > %s AND user_directed = 0 AND (expires_on IS NULL OR expires_on > %s)
			ORDER BY name LIMIT %s
			""",
			(last_name, now, _PAGE),
			as_dict=True,
		)
		if not rows:
			break
		for row in rows:
			counts["scanned"] += 1
			reason = prune_reason(row, config, now)
			if not reason:
				continue
			try:
				_invalidate(row["name"], reason, now)
				counts[reason] += 1
				pruned += 1
			except Exception:
				frappe.log_error(title="AI Memory prune: invalidate failed", message=frappe.get_traceback())
			if pruned >= limit:
				break
		last_name = rows[-1]["name"]

	if pruned:
		frappe.logger("one_bpmn").info(f"AI Memory prune: {counts}")
	return counts
