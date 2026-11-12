# Copyright (c) 2026, one-fm and contributors
"""Countdown before a site update: a System Manager (or a deploy script) starts it, every user's banner follows it.

The end time is kept in the cache as a UTC ISO 8601 string. Each change is also published to all users
as the realtime event ``site_update_countdown``; users who open a page mid-countdown read the state
with ``get_site_update_countdown``.
"""

from datetime import datetime, timedelta, timezone

import frappe
from frappe import _

EVENT = "site_update_countdown"
CACHE_KEY = "one_bpmn:site_update_countdown_ends_at"
DEFAULT_MINUTES = 10
MAX_MINUTES = 120
TIME_FORMAT = "%Y-%m-%dT%H:%M:%SZ"
MANAGER_ROLE = "System Manager"


@frappe.whitelist(methods=["POST"])
def start_site_update_countdown(minutes=DEFAULT_MINUTES) -> dict:
	"""Start (or restart) the countdown and tell every user. Returns {"ends_at", "seconds_remaining"}."""
	frappe.only_for(MANAGER_ROLE)
	minutes = _checked_minutes(minutes)

	ends_at = (_now() + timedelta(minutes=minutes)).replace(microsecond=0)
	frappe.cache.set_value(CACHE_KEY, ends_at.strftime(TIME_FORMAT), expires_in_sec=int(minutes * 60) + 60)

	payload = {"ends_at": ends_at.strftime(TIME_FORMAT), "seconds_remaining": _seconds_until(ends_at)}
	frappe.publish_realtime(EVENT, payload, after_commit=False)
	return payload


@frappe.whitelist()
def get_site_update_countdown() -> dict:
	"""The countdown state for any logged-in user: {"active", "ends_at", "seconds_remaining"}."""
	if frappe.session.user == "Guest":
		frappe.throw(_("Log in to see the site update countdown"), frappe.PermissionError)

	inactive = {"active": False, "ends_at": None, "seconds_remaining": 0}
	stored = frappe.cache.get_value(CACHE_KEY)
	if not stored:
		return inactive

	ends_at = _parse(stored)
	seconds = _seconds_until(ends_at) if ends_at else 0
	if seconds <= 0:
		frappe.cache.delete_value(CACHE_KEY)
		return inactive
	return {"active": True, "ends_at": ends_at.strftime(TIME_FORMAT), "seconds_remaining": seconds}


@frappe.whitelist(methods=["POST"])
def cancel_site_update_countdown() -> dict:
	"""Clear the countdown and tell every user it is cancelled."""
	frappe.only_for(MANAGER_ROLE)
	frappe.cache.delete_value(CACHE_KEY)
	frappe.publish_realtime(EVENT, {"cancelled": True}, after_commit=False)
	return {"cancelled": True}


def _checked_minutes(minutes) -> float:
	try:
		minutes = float(minutes)
	except (TypeError, ValueError):
		frappe.throw(_("Minutes must be a number"))
	if not 0 < minutes <= MAX_MINUTES:
		frappe.throw(_("Minutes must be more than 0 and at most {0}").format(MAX_MINUTES))
	return minutes


def _now() -> datetime:
	return datetime.now(timezone.utc)


def _parse(value) -> datetime | None:
	try:
		return datetime.strptime(str(value), TIME_FORMAT).replace(tzinfo=timezone.utc)
	except ValueError:
		return None


def _seconds_until(ends_at: datetime) -> int:
	return max(0, int((ends_at - _now()).total_seconds()))
