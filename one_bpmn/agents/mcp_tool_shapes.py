# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""
Generate an AI Agent Task's Tools sub-process from the MCP tool registry
(WI-001630, authoring-time only).

An AI Agent Task takes its tools from the shapes of a referenced ad-hoc
sub-process — "tools are the shapes", no registry (WI-001423). Lumina General
Chat hands the LLM the whole MCP surface (32 tools and counting), so authoring
those shapes by hand would mean 32 boxes to draw and re-draw every time a tool is
added or its signature changes.

So the shapes are GENERATED from the live registry instead. Each MCP tool becomes
one Script Task whose:

  * ``id``            is the tool name — which is what the LLM calls, and what
    the shared dispatch script reads back as ``bpmn_id``;
  * ``documentation`` is the tool's own description (Camunda's model: an
    activity's documentation is its tool description);
  * ``aiToolParams``  is the tool's own ``input_schema``, so the model sees the
    exact same argument contract it sees on the direct-API path today.

All 32 shapes point at ONE Server Script — the dispatcher — because the engine
now tells a shape-tool script which shape it is running (``bpmn_id``).

This module is authoring tooling. It runs when someone regenerates the tool
surface; it is NOT part of a chat turn. Nothing here executes tools — the
dispatch script does that at runtime.
"""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET

import frappe
from frappe import _

BPMN_NS = "http://www.omg.org/spec/BPMN/20100524/MODEL"
BPMNDI_NS = "http://www.omg.org/spec/BPMN/20100524/DI"
DC_NS = "http://www.omg.org/spec/DD/20100524/DC"
SPIFF_NS = "http://spiffworkflow.org/bpmn/schema/1.0/core"

# Layout of the generated grid inside the Tools sub-process.
_COLS = 6
_CELL_W = 150
_CELL_H = 90
_BOX_W = 130
_BOX_H = 70
_PAD_X = 20
_PAD_Y = 40


def mcp_tool_specs() -> list:
	"""Every registered MCP tool as ``{name, description, input_schema}``.

	Sorted by name so a regeneration produces a stable diagram instead of
	reshuffling boxes on every run.
	"""
	from onefm_mcp.handle_mcp import mcp

	try:
		import onefm_mcp.mcp_tools  # noqa: F401  (registers the tools)
	except ImportError:
		frappe.log_error(
			title="MCP tool shapes: mcp_tools import failed",
			message=frappe.get_traceback(),
		)

	specs = []
	for name in sorted(mcp._tool_registry):
		entry = mcp._tool_registry[name]
		if isinstance(entry, dict):
			description = (entry.get("description") or "").strip()
			schema = entry.get("input_schema") or {}
		else:
			description = (entry.__doc__ or "").strip()
			schema = {}
		if not isinstance(schema, dict):
			schema = {}
		specs.append({
			"name": name,
			# A tool description is what the model picks on; keep it whole but
			# bounded so 32 of them do not bloat every request.
			"description": " ".join(description.split())[:600] or f"Run the {name} tool.",
			"input_schema": {
				"properties": schema.get("properties") or {},
				"required": schema.get("required") or [],
			},
		})
	return specs


def _cell_bounds(index: int, origin_x: int, origin_y: int) -> tuple:
	row, col = divmod(index, _COLS)
	return (
		origin_x + _PAD_X + col * _CELL_W,
		origin_y + _PAD_Y + row * _CELL_H,
	)


def subprocess_size(count: int) -> tuple:
	rows = max(1, -(-count // _COLS))
	return (_PAD_X * 2 + _COLS * _CELL_W, _PAD_Y + rows * _CELL_H + _PAD_Y // 2)


def render_tool_shapes(specs: list, script_name: str) -> str:
	"""The ``<bpmn:scriptTask>`` elements for the Tools sub-process body."""
	out = []
	for spec in specs:
		params = json.dumps(spec["input_schema"], separators=(",", ":"))
		out.append(
			f'      <bpmn:scriptTask id="{_x(spec["name"])}" name="{_x(spec["name"])}"'
			f' spiffworkflow:serverScript="{_x(script_name)}"'
			f' spiffworkflow:scriptType="Server Script"'
			f' spiffworkflow:scriptName="{_x(script_name)}"'
			f' spiffworkflow:aiToolParams="{_x(params)}">\n'
			f"        <bpmn:documentation>{_x(spec['description'])}</bpmn:documentation>\n"
			f"        <bpmn:script>{_x(script_name)}</bpmn:script>\n"
			f"      </bpmn:scriptTask>"
		)
	return "\n".join(out)


def render_tool_shape_di(specs: list, origin_x: int, origin_y: int) -> str:
	"""The BPMNShape entries that lay the generated tools out in a grid."""
	out = []
	for i, spec in enumerate(specs):
		x, y = _cell_bounds(i, origin_x, origin_y)
		out.append(
			f'      <bpmndi:BPMNShape id="{_x(spec["name"])}_di" bpmnElement="{_x(spec["name"])}">\n'
			f'        <dc:Bounds x="{x}" y="{y}" width="{_BOX_W}" height="{_BOX_H}"/>\n'
			f"      </bpmndi:BPMNShape>"
		)
	return "\n".join(out)


def _x(text: str) -> str:
	"""XML attribute/text escaping (quotes included — these go in attributes)."""
	return (
		str(text)
		.replace("&", "&amp;")
		.replace("<", "&lt;")
		.replace(">", "&gt;")
		.replace('"', "&quot;")
	)


@frappe.whitelist()
def regenerate_mcp_tool_shapes(process_model: str, subprocess_id: str) -> dict:
	"""Rebuild one ad-hoc sub-process's tool shapes from the live MCP registry.

	Replaces only that element (and its DI children) inside the model's diagram,
	so hand edits everywhere else on the canvas survive. Redeploys afterwards so
	the embedded ``aiToolShapes`` the agent reads at dispatch is refreshed.

	Use after adding, removing or re-signing an MCP tool.
	"""
	if "System Manager" not in frappe.get_roles():
		frappe.throw(_("Only a System Manager can regenerate tool shapes."), frappe.PermissionError)
	model = frappe.get_doc("BPMN Process Model", process_model)
	xml = model.bpmn_xml or ""
	if not xml.strip():
		frappe.throw(_("Process model '{0}' has no diagram.").format(process_model))

	ET.register_namespace("bpmn", BPMN_NS)
	ET.register_namespace("bpmndi", BPMNDI_NS)
	ET.register_namespace("dc", DC_NS)
	ET.register_namespace("spiffworkflow", SPIFF_NS)
	root = ET.fromstring(xml.encode("utf-8"))

	adhoc = None
	for el in root.iter(f"{{{BPMN_NS}}}adHocSubProcess"):
		if el.get("id") == subprocess_id:
			adhoc = el
			break
	if adhoc is None:
		frappe.throw(
			_("No ad-hoc sub-process '{0}' in '{1}'.").format(subprocess_id, process_model)
		)

	script_name = ""
	for child in list(adhoc):
		if child.tag == f"{{{BPMN_NS}}}scriptTask":
			script_name = child.get(f"{{{SPIFF_NS}}}serverScript") or script_name
	if not script_name:
		frappe.throw(
			_("Cannot tell which Server Script '{0}' dispatches to — regenerate from the builder instead.").format(
				subprocess_id
			)
		)

	specs = mcp_tool_specs()
	existing = {
		child.get("id")
		for child in adhoc
		if child.tag == f"{{{BPMN_NS}}}scriptTask"
	}
	incoming = {s["name"] for s in specs}

	return {
		"process_model": process_model,
		"subprocess_id": subprocess_id,
		"server_script": script_name,
		"tools_now": sorted(incoming),
		"added": sorted(incoming - existing),
		"removed": sorted(existing - incoming),
		# The caller applies the rewrite: returning the fragment keeps this
		# function a pure diff/report so it can be reviewed before a redeploy
		# rewrites a live diagram.
		"shapes_xml": render_tool_shapes(specs, script_name),
	}
