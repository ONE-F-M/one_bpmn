# Copyright (c) 2026, one-fm and contributors
"""``bench check-agent-tools``: run every agent tool once with empty input after a deploy.

Server Script tools run inside a rolled-back savepoint with commit, enqueue, realtime,
error logging and model calls blocked. Connector tools only have their handler imported. Only an
import-shaped error fails a tool; the command exits 1 when any tool fails.
"""

import json

import click
import frappe
from frappe.commands import get_site, pass_context

from one_bpmn.agents import shape_tools
from one_bpmn.agents.llm_provider import factory
from one_bpmn.one_bpmn.connectors import manifest

_IMPORT_FAILURE_TYPES = (ImportError, SyntaxError, NameError, AttributeError)


class _ModelCallBlocked(Exception):
	"""Raised instead of a real model call during the smoke check."""


async def _blocked_complete(*args, **kwargs):
	raise _ModelCallBlocked("check-agent-tools: model calls are blocked during the smoke check")


def _noop(*args, **kwargs):
	return None


def _is_real_failure(exc: Exception) -> bool:
	"""True for a broken import or name, False for an error caused by the empty input."""
	if not isinstance(exc, _IMPORT_FAILURE_TYPES):
		return False
	return not (isinstance(exc, AttributeError) and str(exc).startswith("'NoneType' object"))


def _empty_value(schema: dict):
	prop_type = (schema or {}).get("type")
	if prop_type in ("number", "integer"):
		return 0
	if prop_type == "boolean":
		return False
	if prop_type == "array":
		return []
	if prop_type == "object":
		return {}
	return ""


def _empty_kwargs(tool: dict) -> dict:
	params = tool.get("parameters") or {}
	if not isinstance(params, dict):
		return {}
	return {name: _empty_value(prop_schema) for name, prop_schema in params.items()}


def _parse_tool_shapes(raw) -> list:
	if isinstance(raw, str):
		try:
			raw = json.loads(raw or "[]")
		except (TypeError, ValueError):
			return []
	return raw if isinstance(raw, list) else []


def _with_shape_config(tool: dict, extensions: dict) -> dict:
	"""The tool entry over its shape's own compiled config, which older specs need for connector wiring."""
	merged = dict(extensions.get(tool.get("bpmn_id")) or {})
	merged.update({k: v for k, v in tool.items() if v not in (None, "")})
	return merged


def _check_server_script(instance, script_name: str, tool: dict, bpmn_id: str) -> str | None:
	"""Failure text for one Server Script tool, or None when it passed."""
	row = frappe.db.get_value("Server Script", script_name, ["name", "disabled"], as_dict=True)
	if not row:
		return f"LookupError: Server Script '{script_name}' not found"
	if row.disabled:
		return f"RuntimeError: Server Script '{script_name}' is disabled"

	task = shape_tools._synthetic_task(bpmn_id, _empty_kwargs(tool))
	savepoint = f"check_agent_tools_{frappe.generate_hash(length=10)}"
	frappe.db.savepoint(savepoint)
	try:
		shape_tools._run_server_script(instance, script_name, task, bpmn_id, shape_config=tool)
	except Exception as exc:
		if _is_real_failure(exc):
			return f"{type(exc).__name__}: {exc}"
	finally:
		frappe.db.rollback(save_point=savepoint)
	return None


def _connector_handler_path(tool: dict) -> str:
	connector_id = (tool.get("connectorId") or "").strip()
	operation = (tool.get("operation") or "").strip()
	if not connector_id or not operation:
		return ""
	spec = manifest.get_execution_spec(connector_id, operation)
	return (spec and spec.handler_path) or ""


def _check_handler_import(handler_path: str) -> str | None:
	"""Failure text when the connector handler cannot be imported, or None."""
	try:
		frappe.get_attr(handler_path)
	except Exception as exc:
		if _is_real_failure(exc):
			return f"{type(exc).__name__}: {exc}"
	return None


def run_check() -> tuple[list[str], int, int]:
	"""Check every tool on every active model; returns (failure_lines, checked, skipped)."""
	checked = 0
	skipped = 0
	failures = []

	original_commit = frappe.db.commit
	original_enqueue = frappe.enqueue
	original_publish_realtime = frappe.publish_realtime
	original_log_error = frappe.log_error
	original_complete = factory.MeteredAdapter.complete

	try:
		frappe.db.commit = _noop
		frappe.enqueue = _noop
		frappe.publish_realtime = _noop
		frappe.log_error = _noop
		factory.MeteredAdapter.complete = _blocked_complete

		models = frappe.get_all(
			"BPMN Process Model",
			filters={"is_active": 1},
			fields=["name", "title", "serialized_spec"],
		)

		for model in models:
			try:
				spec = json.loads(model.serialized_spec or "{}")
			except (TypeError, ValueError):
				continue
			extensions = spec.get("service_task_extensions")
			if not isinstance(extensions, dict):
				continue

			stub_instance = frappe._dict(
				name="check-agent-tools",
				context_doctype="",
				context_docname="",
				_service_task_extensions=extensions,
			)

			seen_tools = set()
			for agent_bpmn_id, cfg in extensions.items():
				if not isinstance(cfg, dict) or cfg.get("serviceType") != "ai_agent":
					continue

				for tool in _parse_tool_shapes(cfg.get("aiToolShapes")):
					if not isinstance(tool, dict):
						continue
					tool_bpmn_id = tool.get("bpmn_id")
					if not tool_bpmn_id or tool_bpmn_id in seen_tools:
						continue
					seen_tools.add(tool_bpmn_id)

					if tool.get("human"):
						skipped += 1
						continue

					tool = _with_shape_config(tool, extensions)
					server_script = tool.get("serverScript")
					handler_path = (
						_connector_handler_path(tool) if tool.get("serviceType") == "connector" else ""
					)

					if server_script:
						outcome = _check_server_script(stub_instance, server_script, tool, tool_bpmn_id)
					elif handler_path:
						outcome = _check_handler_import(handler_path)
					else:
						skipped += 1
						continue

					checked += 1
					if outcome is not None:
						failures.append(f"FAIL {model.title} / {agent_bpmn_id} / {tool_bpmn_id}: {outcome}")
	finally:
		frappe.db.commit = original_commit
		frappe.enqueue = original_enqueue
		frappe.publish_realtime = original_publish_realtime
		frappe.log_error = original_log_error
		factory.MeteredAdapter.complete = original_complete

	return failures, checked, skipped


@click.command("check-agent-tools")
@pass_context
def check_agent_tools(context):
	"""Smoke-check every agent tool on every active BPMN Process Model."""
	site = get_site(context)
	frappe.init(site=site)
	frappe.connect()
	frappe.set_user("Administrator")

	try:
		failures, checked, skipped = run_check()
	finally:
		frappe.destroy()

	for line in failures:
		click.echo(line, err=True)
	click.echo(f"{checked} tools checked, {len(failures)} failed, {skipped} skipped")
	raise SystemExit(1 if failures else 0)
