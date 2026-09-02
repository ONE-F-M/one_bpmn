# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""
Add the "sandbox_tool_defs" ad-hoc sub-process to the Dev Agent's BPMN map —
schema-only shapes the sandbox's own coding loop executes, never Processa
(see api/compilation.py::_resolve_sandbox_tool_shapes/_validate_sandbox_tools
for the compile-time half of this mechanism, and connectors/agent_sandbox_ops.py
::_sandbox_tools for how the extracted schemas reach the sandbox).

Mirrors mcp_tool_shapes.py's shape: a fixed spec list, rendered as raw XML
via string templates (not an ElementTree round-trip of the whole document —
that risks reformatting a hand-authored diagram in ways that could disturb
bpmn-js's own editing of it later). Unlike mcp_tool_shapes.py's own
regenerate_mcp_tool_shapes (a pure diff/report the caller applies), this
module's add_sandbox_tool_defs() does the full splice + save + redeploy
itself — this is a one-time addition to a known, fixed tool set, not an
ongoing regeneration workflow.

This module was written without ever seeing the real, live "Dev Agent"
diagram (it ships by export/import, not in this repo — see
patches/v1_0/seed_dev_agent_config.py's own docstring) — add_sandbox_tool_defs
locates its target defensively (by the connector's functional identity,
connectorId="agent_sandbox"/operation="dispatch", not by guessing the
shape's own diagram id) and fails loudly with a specific reason rather than
guessing, so a genuine structural mismatch is reported, not silently
skipped or worse, misapplied.
"""

from __future__ import annotations

import json
import re

import frappe
from frappe import _

BPMN_NS = "http://www.omg.org/spec/BPMN/20100524/MODEL"
SPIFF_NS = "http://spiffworkflow.org/bpmn/schema/1.0/core"

SANDBOX_TOOL_DEFS_ID = "sandbox_tool_defs"

# One entry per tool dev_agent_server.py's _dispatch_tool actually
# implements (_KNOWN_TOOL_NAMES) — keep these two lists in sync by hand;
# there is no shared source between the two repos to enforce it automatically.
SANDBOX_TOOL_SPECS = [
	{
		"name": "read_file",
		"label": "Read a file",
		"shape": "script",
		"server_script": "Sandbox Tool: Read File",
		"description": "Read one file's current content from the target app's working tree.",
		"parameters": {"path": {"type": "string", "description": "Repo-relative file path."}},
		"required": ["path"],
	},
	{
		"name": "write_file",
		"label": "Write a file",
		"shape": "script",
		"server_script": "Sandbox Tool: Write File",
		"description": (
			"Write a file's COMPLETE content into the target app's working tree, creating it if "
			"it does not exist. Overwrites the whole file — always include every line, not a diff."
		),
		"parameters": {
			"path": {"type": "string", "description": "Repo-relative file path."},
			"content": {"type": "string", "description": "The file's full new content."},
		},
		"required": ["path", "content"],
	},
	{
		"name": "edit_file",
		"label": "Edit a file",
		"shape": "script",
		"server_script": "Sandbox Tool: Edit File",
		"description": (
			"Replace one exact, unique occurrence of old_string with new_string in an existing "
			"file — for a small, targeted change where rewriting the whole file with write_file "
			"would be wasteful. old_string must match exactly once; include enough surrounding "
			"context to make it unique."
		),
		"parameters": {
			"path": {"type": "string", "description": "Repo-relative file path."},
			"old_string": {"type": "string", "description": "Exact text to replace — must appear exactly once."},
			"new_string": {"type": "string", "description": "Text to replace it with."},
		},
		"required": ["path", "old_string", "new_string"],
	},
	{
		"name": "list_files",
		"label": "List files",
		"shape": "script",
		"server_script": "Sandbox Tool: List Files",
		"description": "List file paths in the target app's working tree, optionally scoped to a prefix.",
		"parameters": {
			"path_prefix": {"type": "string", "description": "Optional repo-relative prefix to narrow the listing."},
		},
		"required": [],
	},
	{
		"name": "run_tests",
		"label": "Run the test suite",
		"shape": "service",
		"operation": "run_tests",
		"description": (
			"Run the target app's real test suite against the working tree as it currently stands. "
			"Use this to check your own work before you finish — open_pull_request re-runs tests "
			"itself before opening, but that only decides pass/fail, it doesn't help you fix anything."
		),
		"parameters": {},
		"required": [],
	},
	{
		"name": "open_pull_request",
		"label": "Open the pull request",
		"shape": "service",
		"operation": "open_pull_request",
		"description": (
			"Open (or update, on a retry of the same work order) a pull request with every change "
			"made so far. Re-runs the real test suite itself first and marks the PR clearly if it "
			"fails — call this when you are done, WHETHER OR NOT tests passed. A change that never "
			"reaches a pull request is a change nobody can review."
		),
		"parameters": {
			"summary": {"type": "string", "description": "Plain-words summary of what changed, for the PR body."},
		},
		"required": ["summary"],
	},
]


def _x(text: str) -> str:
	"""XML attribute/text escaping (quotes included — these go in attributes),
	identical to mcp_tool_shapes.py's own helper."""
	return (
		str(text)
		.replace("&", "&amp;")
		.replace("<", "&lt;")
		.replace(">", "&gt;")
		.replace('"', "&quot;")
	)


def _render_tool_shapes(specs: list) -> str:
	"""Mixed Script Task / Service Task styling, matching how the real
	Orchestrator Agent's own tool shapes look (orchestrator_tools: Script
	Tasks with serverScript+a literal <bpmn:script> for its Work Item
	helpers, Service Tasks with connectorId/operation for its A2A
	delegates) — not the uniform generic shape this module used at first,
	which is what looked wrong next to that convention. Every shape here is
	still schema-only regardless of which style it uses: nothing in
	sandbox_tool_defs is ever reached by a sequence flow, so a Script Task's
	<bpmn:script>pass</bpmn:script> body and a Service Task's connectorId/
	operation are never actually run by this engine — only their
	aiToolParams/documentation are ever read, by _extract_tool_shapes at
	compile time."""
	out = []
	for spec in specs:
		params = json.dumps({"properties": spec["parameters"], "required": spec["required"]}, separators=(",", ":"))
		if spec["shape"] == "script":
			out.append(
				f'      <bpmn:scriptTask id="{_x(spec["name"])}" name="{_x(spec["label"])}"'
				f' spiffworkflow:serverScript="{_x(spec["server_script"])}"'
				f' spiffworkflow:scriptType="Server Script"'
				f' spiffworkflow:scriptName="{_x(spec["server_script"])}"'
				f' spiffworkflow:aiToolParams="{_x(params)}">\n'
				f"        <bpmn:documentation>{_x(spec['description'])}</bpmn:documentation>\n"
				f"        <bpmn:script>pass</bpmn:script>\n"
				f"      </bpmn:scriptTask>"
			)
		else:
			out.append(
				f'      <bpmn:serviceTask id="{_x(spec["name"])}" name="{_x(spec["label"])}"'
				f' spiffworkflow:serviceType="connector"'
				f' spiffworkflow:connectorId="agent_sandbox"'
				f' spiffworkflow:operation="{_x(spec["operation"])}"'
				f' spiffworkflow:aiToolParams="{_x(params)}">\n'
				f"        <bpmn:documentation>{_x(spec['description'])}</bpmn:documentation>\n"
				f"      </bpmn:serviceTask>"
			)
	return "\n".join(out)


def _render_tool_shape_di(specs: list, origin_x: int, origin_y: int) -> str:
	"""Simple horizontal row — the CLAUDE.md layout convention (a 3-tool box
	at 550x240) scaled to however many tools this sub-process holds."""
	box_w, box_h, gap = 150, 80, 40
	out = [
		f'      <bpmndi:BPMNShape id="{SANDBOX_TOOL_DEFS_ID}_di" bpmnElement="{SANDBOX_TOOL_DEFS_ID}">\n'
		f'        <dc:Bounds x="{origin_x}" y="{origin_y}"'
		f' width="{len(specs) * (box_w + gap) + gap}" height="{box_h + 80}"/>\n'
		f"      </bpmndi:BPMNShape>"
	]
	for i, spec in enumerate(specs):
		x = origin_x + gap + i * (box_w + gap)
		y = origin_y + 60
		out.append(
			f'      <bpmndi:BPMNShape id="{_x(spec["name"])}_di" bpmnElement="{_x(spec["name"])}">\n'
			f'        <dc:Bounds x="{x}" y="{y}" width="{box_w}" height="{box_h}"/>\n'
			f"      </bpmndi:BPMNShape>"
		)
	return "\n".join(out)


class SandboxToolDefsError(Exception):
	"""Raised when the diagram's structure doesn't match what this module
	needs to locate/splice safely — reported with the specific reason, never
	silently skipped or guessed at."""


def add_sandbox_tool_defs(process_model: str = "Dev Agent") -> dict:
	"""Splice sandbox_tool_defs into *process_model*'s diagram and point the
	agent_sandbox/dispatch connector shape at it via sandboxToolsAdhoc, then
	redeploy. Idempotent — a shape that already carries sandboxToolsAdhoc is
	left untouched and reported, not duplicated.

	Locates the connector shape by its FUNCTIONAL identity
	(connectorId="agent_sandbox", operation="dispatch") rather than assuming
	a specific diagram id — the real "Dev Agent" map isn't in this repo (it
	arrives by export/import), so its shapes' own ids were never seen while
	writing this.

	Returns {"applied": bool, "reason": str} — never raises for "nothing to
	do" or "already applied"; raises SandboxToolDefsError only when the
	diagram exists but doesn't match what's needed to proceed safely.
	"""
	if not frappe.db.exists("BPMN Process Model", process_model):
		return {"applied": False, "reason": f"No '{process_model}' process model on this site yet."}

	model = frappe.get_doc("BPMN Process Model", process_model)
	xml = model.bpmn_xml or ""
	if not xml.strip():
		return {"applied": False, "reason": f"'{process_model}' has no diagram XML yet."}

	if f'id="{SANDBOX_TOOL_DEFS_ID}"' in xml:
		return {"applied": False, "reason": f"'{SANDBOX_TOOL_DEFS_ID}' already present — nothing to do."}

	# Locate the connector shape's opening tag by functional identity. A
	# non-greedy match up to the tag's own close ('>' or '/>') — BPMN
	# attribute order isn't fixed, so this can't assume connectorId comes
	# right before operation or vice versa; two passes confirm both are on
	# the SAME tag.
	service_task_pattern = re.compile(r"<bpmn:serviceTask\b[^>]*?/?>", re.DOTALL)
	target_tag = None
	for match in service_task_pattern.finditer(xml):
		tag = match.group(0)
		if 'spiffworkflow:connectorId="agent_sandbox"' in tag and 'spiffworkflow:operation="dispatch"' in tag:
			target_tag = tag
			break

	if target_tag is None:
		raise SandboxToolDefsError(
			_(
				"No <bpmn:serviceTask> in '{0}' has both connectorId=\"agent_sandbox\" and "
				"operation=\"dispatch\" — cannot tell which shape to point at sandbox_tool_defs. "
				"Check the diagram was imported and the connector shape's operation is still "
				"'dispatch' before re-running this."
			).format(process_model)
		)

	if "spiffworkflow:sandboxToolsAdhoc=" in target_tag:
		return {"applied": False, "reason": "The dispatch shape already carries a sandboxToolsAdhoc reference."}

	# Insert the new attribute right before the tag's own close, preserving
	# every existing attribute and self-closing style untouched.
	self_closing = target_tag.rstrip().endswith("/>")
	insert_at = target_tag.rfind("/>") if self_closing else target_tag.rfind(">")
	new_tag = (
		f'{target_tag[:insert_at]} spiffworkflow:sandboxToolsAdhoc="{SANDBOX_TOOL_DEFS_ID}"{target_tag[insert_at:]}'
	)
	xml = xml.replace(target_tag, new_tag, 1)

	if "</bpmn:process>" not in xml or "</bpmndi:BPMNPlane>" not in xml:
		raise SandboxToolDefsError(
			_("'{0}' is missing </bpmn:process> or </bpmndi:BPMNPlane> — not a well-formed diagram.").format(
				process_model
			)
		)

	adhoc_xml = (
		f'    <bpmn:adHocSubProcess id="{SANDBOX_TOOL_DEFS_ID}" name="Sandbox Tools">\n'
		"      <bpmn:documentation>The tools the sandbox's own coding loop can use — read, write, "
		"edit, list files, run the real test suite, and open the pull request. Schema-only: these "
		"shapes are never executed by Processa itself, only extracted and forwarded (as "
		"payload[\"tools\"]) into the single dispatch_to_sandbox call, where the sandbox's own "
		"internal loop decides which to use and runs every one of them itself.</bpmn:documentation>\n"
		f"{_render_tool_shapes(SANDBOX_TOOL_SPECS)}\n"
		f"    </bpmn:adHocSubProcess>\n  </bpmn:process>"
	)
	xml = xml.replace("</bpmn:process>", adhoc_xml, 1)

	# Origin chosen well clear of typical existing content (CLAUDE.md's own
	# lane-at-y=180 convention leaves y >= 600 free on every live map this
	# session has seen referenced) — a purely cosmetic starting position a
	# person can drag on the canvas afterward if it overlaps anything.
	di_xml = f"{_render_tool_shape_di(SANDBOX_TOOL_SPECS, 100, 600)}\n  </bpmndi:BPMNPlane>"
	xml = xml.replace("</bpmndi:BPMNPlane>", di_xml, 1)

	model.bpmn_xml = xml
	model.save(ignore_permissions=True)

	from one_bpmn.api.compilation import compile_process_model

	compile_process_model(process_model)

	return {"applied": True, "reason": f"Added {SANDBOX_TOOL_DEFS_ID} with {len(SANDBOX_TOOL_SPECS)} tools."}
