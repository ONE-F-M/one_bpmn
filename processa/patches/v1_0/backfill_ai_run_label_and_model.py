# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""
Backfill ``process_model`` and ``bpmn_label`` on existing AI Agent Run records.

- ``process_model`` is resolved by joining through the linked
  BPMN Process Instance.
- ``bpmn_label`` is resolved by parsing the BPMN XML from the
  Process Model and extracting the ``name`` attribute for the
  matching element ID.
"""
from __future__ import annotations

import frappe
from frappe.query_builder import DocType
from frappe.utils import cstr


def execute():
	"""Backfill process_model and bpmn_label on AI Agent Run."""
	Run = DocType("AI Agent Run")
	Instance = DocType("BPMN Process Instance")

	# ── Step 1: Backfill process_model via instance join ──────────
	runs_missing_model = (
		frappe.qb.from_(Run)
		.join(Instance).on(Run.instance == Instance.name)
		.select(Run.name, Instance.process_model)
		.where(
			(Run.process_model.isnull()) | (Run.process_model == "")
		)
	).run(as_dict=True)

	for row in runs_missing_model:
		if row.get("process_model"):
			frappe.db.set_value(
				"AI Agent Run", row["name"],
				"process_model", row["process_model"],
				update_modified=False,
			)

	if runs_missing_model:
		frappe.db.commit()

	# ── Step 2: Backfill bpmn_label by parsing BPMN XML ──────────
	runs_missing_label = frappe.get_all(
		"AI Agent Run",
		filters=[
			["bpmn_label", "in", ["", None]],
			["process_model", "is", "set"],
		],
		fields=["name", "bpmn_id", "process_model"],
	)

	if not runs_missing_label:
		return

	# Group by process_model to avoid re-parsing the same XML
	from collections import defaultdict
	by_model = defaultdict(list)
	for row in runs_missing_label:
		by_model[row["process_model"]].append(row)

	for model_name, rows in by_model.items():
		bpmn_xml = frappe.db.get_value(
			"BPMN Process Model", model_name, "bpmn_xml"
		)
		if not bpmn_xml:
			continue

		# Build a map of id → name from the XML
		label_map = _parse_element_labels(bpmn_xml)

		for row in rows:
			label = label_map.get(row["bpmn_id"], "")
			if label:
				frappe.db.set_value(
					"AI Agent Run", row["name"],
					"bpmn_label", label,
					update_modified=False,
				)

	frappe.db.commit()


def _parse_element_labels(bpmn_xml: str) -> dict:
	"""Parse BPMN XML and return a dict of {element_id: element_name}."""
	import xml.etree.ElementTree as ET

	label_map = {}
	try:
		root = ET.fromstring(bpmn_xml)
		# Walk all elements looking for 'id' and 'name' attributes
		for elem in root.iter():
			elem_id = elem.get("id")
			elem_name = elem.get("name")
			if elem_id and elem_name:
				label_map[elem_id] = cstr(elem_name).strip()
	except Exception:
		frappe.log_error(
			title="Backfill bpmn_label: XML parse error",
			message=frappe.get_traceback(),
		)

	return label_map
