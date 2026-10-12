# Copyright (c) 2026, one-fm and contributors
"""``bench list-agents-without-provider``: configurations whose AI Model has no provider link."""

import click
import frappe
from frappe.commands import get_site, pass_context
from frappe.query_builder import DocType


def configs_without_provider() -> list[dict]:
	"""Configurations with an ai_model whose AI Model record is missing or has no provider."""
	config = DocType("AI Agent Configuration")
	model = DocType("AI Model")
	return (
		frappe.qb.from_(config)
		.left_join(model)
		.on(model.name == config.ai_model)
		.select(config.name, config.ai_model, config.ai_provider, config.enabled)
		.where(config.ai_model.isnotnull() & (config.ai_model != ""))
		.where(model.provider.isnull() | (model.provider == ""))
		.orderby(config.name)
	).run(as_dict=True)


@click.command("list-agents-without-provider")
@pass_context
def list_agents_without_provider(context):
	"""List AI Agent Configurations whose model has no provider link."""
	frappe.init(site=get_site(context))
	frappe.connect()
	try:
		rows = configs_without_provider()
		for row in rows:
			click.echo(
				f"{row.name}\tmodel={row.ai_model}\tconfig_provider={row.ai_provider or '-'}\tenabled={row.enabled}"
			)
		click.echo(f"{len(rows)} configuration(s) whose model has no provider.")
	finally:
		frappe.destroy()
