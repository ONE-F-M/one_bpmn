"""Remove aiMaxTokens values of 0, blank or below 0 from every map's shapes.

Compile now refuses them. At runtime they already fell back to the default, so
removing the attribute changes nothing about how a map runs.
"""

import re

import frappe

MAX_TOKENS_ATTR = re.compile(r'\s+(?:[\w-]+:)?aiMaxTokens="([^"]*)"')


def execute():
	models = frappe.get_all(
		"BPMN Process Model",
		filters={"bpmn_xml": ["like", "%aiMaxTokens%"]},
		fields=["name", "bpmn_xml"],
	)
	changed = 0
	for model in models:
		cleaned, removed = strip_non_positive_max_tokens(model.bpmn_xml or "")
		if not removed:
			continue
		frappe.db.set_value("BPMN Process Model", model.name, "bpmn_xml", cleaned, update_modified=False)
		changed += 1
		print(f"{model.name}: removed {removed} aiMaxTokens value(s)")
	print(f"aiMaxTokens clean-up: {changed} map(s) changed")


def strip_non_positive_max_tokens(bpmn_xml: str) -> tuple[str, int]:
	"""Return the XML without non-positive aiMaxTokens attributes, and how many were removed."""
	removed = 0

	def _drop(match):
		nonlocal removed
		value = match.group(1).strip()
		if value.isdigit() and int(value) > 0:
			return match.group(0)
		removed += 1
		return ""

	return MAX_TOKENS_ATTR.sub(_drop, bpmn_xml), removed
