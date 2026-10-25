"""Queues the first DMS search index build for every Active Document Register entry."""

import frappe

from one_bpmn.agents.dms_search import DOCTYPE, enqueue_reindex


def execute():
	for name in frappe.get_all(DOCTYPE, filters={"lifecycle_state": "Active"}, pluck="name"):
		enqueue_reindex(frappe._dict(name=name))
