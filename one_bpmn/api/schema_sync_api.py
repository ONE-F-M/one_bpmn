# Copyright (c) 2026, ONE BPMN and contributors
# For license information, please see license.txt
#
# BA-side API endpoint: called BY the Production site to pull delta records
# of Custom DocTypes, Custom Fields, and Property Setters.

import frappe
from frappe import _
from frappe.utils import get_datetime


# Fields to exclude when exporting records (internal Frappe metadata)
_EXCLUDE_FIELDS = {"_user_tags", "_comments", "_assign", "_liked_by"}


def _get_records(doctype: str, since: str | None, fields: list[str] | None = None) -> list[dict]:
	"""Fetch records from a given DocType, optionally filtered by modification time.

	Args:
		doctype: The DocType to query (e.g., "Custom Field").
		since: ISO datetime string. If provided, only records modified on or after
			this timestamp are returned. If None, all records are returned.
		fields: Optional list of fields to fetch. If None, fetches all via get_doc.

	Returns:
		List of document dicts with all field values.
	"""
	filters = {}
	if since:
		filters["modified"] = [">=", since]

	# Get names first, then full docs for complete data
	names = frappe.get_all(
		doctype,
		filters=filters,
		pluck="name",
		order_by="modified asc",
	)

	records = []
	for name in names:
		doc = frappe.get_doc(doctype, name)
		doc_dict = doc.as_dict()
		# Remove internal fields
		for field in _EXCLUDE_FIELDS:
			doc_dict.pop(field, None)
		records.append(doc_dict)

	return records


@frappe.whitelist(methods=["GET"])
def get_schema_delta(since: str = None) -> dict:
	"""Return Custom Fields and Property Setters delta.

	Called by the Production site to pull records that were created or
	modified since the given timestamp.

	Args:
		since: ISO datetime string (e.g., "2026-06-14 00:00:00").
			If None or empty, returns ALL records (full sync).

	Returns:
		dict with keys:
			- custom_fields: list of Custom Field dicts
			- property_setters: list of Property Setter dicts
			- sync_timestamp: server timestamp at the time of extraction
	"""
	frappe.only_for("System Manager")

	# Normalize the since parameter
	if since and isinstance(since, str):
		since = since.strip()
		if not since:
			since = None

	# Validate the datetime format if provided
	if since:
		try:
			get_datetime(since)
		except Exception:
			frappe.throw(
				_("Invalid datetime format for 'since' parameter: {0}").format(since),
				title=_("Validation Error"),
			)

	result = {
		"custom_fields": _get_records("Custom Field", since),
		"property_setters": _get_records("Property Setter", since),
		"sync_timestamp": frappe.utils.now_datetime().isoformat(),
	}

	return result
