# Copyright (c) 2026, one-fm and contributors
"""``bench list-agent-drift``: every AI shape on an active map whose prompt, model, temperature or max tokens differ from its linked configuration. Exits 1 when any does."""

import click
import frappe
from frappe.commands import get_site, pass_context


@click.command("list-agent-drift")
@pass_context
def list_agent_drift(context):
	"""List drift between AI shapes and their configurations across all deployed maps."""
	frappe.init(site=get_site(context))
	frappe.connect()
	try:
		lines = drift_lines()
	finally:
		frappe.destroy()

	for line in lines:
		click.echo(line)
	click.echo(f"{len(lines)} AI shapes differ from their configuration")
	raise SystemExit(1 if lines else 0)


def drift_lines() -> list[str]:
	from one_bpmn.api.compilation import (
		_check_shape_config_drift,
		_extract_adhoc_selector_config,
		_extract_service_task_config,
	)

	lines = []
	for model in frappe.get_all("BPMN Process Model", filters={"is_active": 1}, fields=["name", "bpmn_xml"], order_by="name"):
		extensions = _extract_service_task_config(model.bpmn_xml or "")
		extensions.update(_extract_adhoc_selector_config(model.bpmn_xml or ""))
		lines.extend(f"{model.name}: {w['detail']}" for w in _check_shape_config_drift(extensions))
	return lines
