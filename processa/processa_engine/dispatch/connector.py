# Copyright (c) 2026, one-fm and contributors
"""Service Task serviceType="connector": run a BPMN Connector Operation."""

import html
import json

import frappe

from processa.processa_engine.dispatch.common import cfg_truthy

# Where dispatch_connector records what happened; the tool loop reads it and hides it from the model.
CONNECTOR_OUTCOME_KEY = "_bpmn_connector_outcome"


def dispatch_connector(instance, task, task_cfg: dict, bpmn_id: str) -> None:
	"""Run connectorId/operation with connectorParams (Jinja-rendered, then the field's Value Transform).

	The handler's return lands in task.data[resultVariable]. Errors are logged and the flow continues unless failOnError is set.
	"""
	from processa.processa_connectors import manifest as _manifest

	connector_id = (task_cfg.get("connectorId") or "").strip()
	operation = (task_cfg.get("operation") or "").strip()
	result_var = (task_cfg.get("resultVariable") or "").strip()
	fail_on_error = cfg_truthy(task_cfg.get("failOnError"))

	def outcome(status, **detail):
		task.data[CONNECTOR_OUTCOME_KEY] = {
			"connector": f"{connector_id}/{operation}".strip("/"), "status": status, **detail
		}

	# Checked against the user the instance runs as, so a diagram cannot run a connector its user may not.
	if not _manifest.user_may_use_connector(connector_id):
		frappe.log_error(
			title=f"BPMN ServiceTask: connector not permitted ({bpmn_id})",
			message=(
				f"{frappe.session.user} lacks a role allowed to use connector "
				f"{connector_id!r} (operation {operation!r})."
			),
		)
		outcome("not_permitted")
		if fail_on_error:
			frappe.throw(f"Not permitted to use connector {connector_id}")
		return

	handler = _resolve_connector_handler(connector_id, operation)
	if not handler:
		frappe.log_error(
			title=f"BPMN ServiceTask: connector unknown ({bpmn_id})",
			message=(
				f"No executor for connectorId={connector_id!r} operation={operation!r}. "
				f"Either it is not a BPMN Connector Operation, it is disabled, or its "
				f"row names neither an HTTP request nor a Handler Path."
			),
		)
		outcome("not_run", reason="unknown or disabled connector operation")
		if fail_on_error:
			frappe.throw(f"Unknown connector {connector_id}/{operation}")
		return

	raw_params = task_cfg.get("connectorParams") or "{}"
	try:
		params = json.loads(raw_params) if isinstance(raw_params, str) else dict(raw_params or {})
		if not isinstance(params, dict):
			raise ValueError("connectorParams must be a JSON object")
	except Exception:
		frappe.log_error(
			title=f"BPMN ServiceTask: connector params invalid ({bpmn_id})",
			message=f"connectorParams is not a JSON object: {raw_params!r}",
		)
		outcome("not_run", reason="connectorParams is not a JSON object")
		if fail_on_error:
			raise
		return

	doc = (
		frappe.get_doc(instance.context_doctype, instance.context_docname)
		if (instance.context_doctype and instance.context_docname)
		else frappe._dict()
	)
	render_ctx = {"doc": doc, "instance": instance, "frappe": frappe, "task_data": dict(task.data)}
	specs = _manifest.field_specs(connector_id, operation)
	transforms = _manifest.field_transforms(connector_id, operation)

	resolved = {}
	for key, value in params.items():
		spec = specs.get(key, {})
		val = value
		expression = spec.get("expression", True)
		# connectorParams comes from an XML attribute, so entities such as &#39; can reach the template.
		if isinstance(val, str) and expression:
			val = html.unescape(val)
		if isinstance(val, str) and expression and ("{{" in val or "{%" in val):
			try:
				val = frappe.render_template(val, render_ctx)
			except Exception:
				frappe.log_error(
					title=f"BPMN ServiceTask: connector Jinja render failed ({bpmn_id})",
					message=f"field={key!r}\n\n{frappe.get_traceback()}",
				)
		val = _apply_value_transform(transforms.get(key), val, key, bpmn_id)
		resolved[key] = val

	# operation lets one handler serve several named operations of a connector.
	ctx = {"instance": instance, "task": task, "doc": doc, "task_data": dict(task.data), "operation": operation}
	output = None
	try:
		output = handler(resolved, ctx)
	except Exception as exc:
		frappe.log_error(
			title=f"BPMN ServiceTask: connector {connector_id}/{operation} failed ({bpmn_id})",
			message=frappe.get_traceback(),
		)
		outcome("failed", error=str(exc)[:200])
		if fail_on_error:
			raise
	else:
		outcome("ok", returned=output is not None, stored=bool(result_var))

	if result_var:
		task.data[result_var] = output


def _resolve_connector_handler(connector_id: str, operation: str):
	"""The operation's Handler Path, or the HTTP Request executor; None when the operation names neither."""
	from processa.processa_connectors import manifest as _manifest

	try:
		spec = _manifest.get_execution_spec(connector_id, operation)
	except Exception:
		frappe.log_error(
			title=f"BPMN ServiceTask: connector config unreadable ({connector_id}/{operation})",
			message=frappe.get_traceback(),
		)
		spec = None

	if spec:
		if spec.handler_path:
			try:
				return frappe.get_attr(spec.handler_path)
			except Exception:
				frappe.log_error(
					title=f"BPMN ServiceTask: connector handler path failed ({connector_id}/{operation})",
					message=f"handler_path={spec.handler_path!r}\n\n{frappe.get_traceback()}",
				)
				return None

		if spec.execution_type == "HTTP Request":
			from processa.processa_connectors.operations import http as http_ops

			return lambda params, ctx: http_ops.execute(spec, params, ctx)

	return None


def _apply_value_transform(path: str, value, field_name: str, bpmn_id: str):
	"""Run the field's Value Transform (a dotted path to fn(value)); a failing transform is logged and the value kept."""
	path = (path or "").strip()
	if not path or value in (None, ""):
		return value
	try:
		return frappe.get_attr(path)(value)
	except Exception:
		frappe.log_error(
			title=f"BPMN ServiceTask: connector value transform failed ({bpmn_id})",
			message=f"field={field_name!r} transform={path!r}\n\n{frappe.get_traceback()}",
		)
		return value
