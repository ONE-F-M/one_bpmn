"""Date windows, buckets and the run filters that every Insights report shares."""
from __future__ import annotations

from datetime import timedelta
from typing import Optional

from frappe.query_builder import functions as fn
from frappe.utils import add_days, cstr, getdate, today


def default_dates(from_date: Optional[str], to_date: Optional[str], days: int = 7):
	"""Return (from_date, to_date) defaulting to the last *days* days."""
	to_d = getdate(to_date) if to_date else getdate(today())
	from_d = getdate(from_date) if from_date else getdate(add_days(today(), -(days - 1)))
	return from_d, to_d


def origin_condition(Run, origin: str):
	"""qb criterion for the run-origin segment.

	"production" (default) excludes eval-origin runs — rows created before the
	origin field existed are NULL and count as production. "eval" selects only
	eval-origin runs. "all" applies no filter.
	"""
	if origin == "eval":
		return Run.origin == "eval"
	if origin == "all":
		return Run.name.notnull()
	return fn.Coalesce(Run.origin, "production") != "eval"


def previous_period(from_d, to_d):
	"""Same-length window ending the day before *from_d* (see work order)."""
	length = (to_d - from_d).days
	previous_to = add_days(from_d, -1)
	previous_from = add_days(previous_to, -length)
	return getdate(previous_from), getdate(previous_to)


def grain_for(from_d, to_d) -> str:
	span = (to_d - from_d).days + 1
	if span <= 31:
		return "day"
	if span <= 120:
		return "week"
	return "month"


def bucket_start(d, grain: str):
	d = getdate(d)
	if grain == "week":
		return d - timedelta(days=d.weekday())
	if grain == "month":
		return d.replace(day=1)
	return d


def list_bucket_labels(from_d, to_d, grain: str) -> list:
	"""Ordered, de-duplicated bucket-start labels spanning the range."""
	labels = {}
	d = from_d
	while d <= to_d:
		labels[cstr(bucket_start(d, grain))] = True
		d = getdate(add_days(cstr(d), 1))
	return list(labels)


def apply_common_filters(query, Run, model=None, provider=None, process_model=None, agent_configuration=None):
	if model:
		query = query.where(Run.model == model)
	if provider:
		query = query.where(Run.provider == provider)
	if process_model:
		query = query.where(Run.process_model == process_model)
	if agent_configuration:
		query = query.where(Run.agent_configuration == agent_configuration)
	return query


def apply_conditions(query, conditions):
	for condition in conditions:
		query = query.where(condition)
	return query
