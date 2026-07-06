# Copyright (c) 2026, one-fm and contributors
# WI-001353 (2-03): tool-pool resolution — merge diagram tasks and registry.

from dataclasses import dataclass

import frappe
from SpiffWorkflow.bpmn.specs.control import BpmnStartTask, SimpleBpmnTask, _EndJoin
from SpiffWorkflow.bpmn.specs.mixins.subworkflow_task import SubWorkflowTask
from SpiffWorkflow.specs import MultiChoice

from one_bpmn.agents.llm_provider.base import ToolSpec

DIAGRAM_TASK = "diagram_task"
REGISTRY_TOOL = "registry_tool"


@dataclass
class ToolCandidate:
	"""One selector candidate: a ToolSpec plus where it came from.

	spec is the exact shape the agents/llm_provider tool-calling loops
	consume (name, description, parameters, required); source tells the
	dispatcher whether choosing it means activating a diagram task or
	invoking a registry tool handler.
	"""

	spec: ToolSpec
	source: str


def resolve_tool_pool(subworkflow, task_cfg: dict, process_model: str | None = None) -> list:
	"""
	Build the unified candidate list an AI Task Selector chooses from.

	Per the merged-pool design, the pool is the union of:
	- the ad-hoc subprocess's own inner head tasks (Camunda's model — each
	  task's documentation doubles as its tool description), when
	  aiToolSources is "diagram" or "both"
	- enabled AI Agent Tool records whose applicable_processes is empty
	  (global) or contains ``process_model``, when aiToolSources is
	  "registry" or "both"

	Name collisions between the two halves are rejected at diagram-compile
	time (api/compilation.py) so designers see the error while editing;
	this function assumes a validated diagram.

	Args:
	    subworkflow:   the ad-hoc BpmnSubWorkflow (its spec's start.outputs
	                   are the candidate task specs)
	    task_cfg:      the selector's task_cfg (WI-001351) — reads
	                   aiToolSources, defaulting to "both"
	    process_model: BPMN Process Model name for registry scoping

	Returns:
	    list[ToolCandidate]
	"""
	sources = (task_cfg or {}).get("aiToolSources") or "both"
	pool = []

	if sources in ("diagram", "both"):
		pool.extend(_diagram_candidates(subworkflow))

	if sources in ("registry", "both"):
		pool.extend(_registry_candidates(process_model))

	return pool


def resolve_agent_tools(allowed_tool_names, process_model: str | None = None) -> list:
	"""
	Resolve a standalone AI Agent Task's explicit tool allow-list into ToolSpecs.

	Unlike the selector's resolve_tool_pool — which offers a whole pool the LLM
	chooses an *activation* from — an AI Agent Task carries an explicit list of
	the registry tools it may call, attached to THIS shape (mirroring Camunda's
	AI Agent Task connector, where tools belong to the agent). Only tools that
	(a) are named in ``allowed_tool_names``, (b) are active, and (c) apply to
	``process_model`` are returned; unknown/inactive/out-of-scope names are
	skipped here (compile-time validation surfaces them to the designer).

	Args:
	    allowed_tool_names: iterable of AI Agent Tool names (== tool_name, since
	                        the doctype autonames by that field)
	    process_model:      BPMN Process Model name, for registry scoping

	Returns:
	    list[ToolSpec] — ready for ExecutorConfig.tools / the adapter tool loop.
	"""
	from one_bpmn.agents.tool_registry import compile_tool_spec

	specs = []
	seen = set()
	for raw_name in allowed_tool_names or []:
		name = (raw_name or "").strip()
		if not name or name in seen:
			continue
		seen.add(name)
		if not frappe.db.exists("AI Agent Tool", name):
			continue
		doc = frappe.get_doc("AI Agent Tool", name)
		if not doc.is_active:
			continue
		if not _applies_to_process(doc, process_model):
			continue
		specs.append(compile_tool_spec(doc))
	return specs


def _diagram_candidates(subworkflow) -> list:
	candidates = []
	for spec in _candidate_task_specs(subworkflow.spec):
		bpmn_id = getattr(spec, "bpmn_id", None) or spec.name
		description = (spec.documentation or "").strip() or spec.description or bpmn_id
		candidates.append(
			ToolCandidate(
				spec=ToolSpec(
					# Diagram tasks are ACTIVATED by the dispatch loop
					# (WI-001352), not called as functions.
					fn=None,
					name=bpmn_id,
					description=description,
					parameters={},
					required=[],
				),
				source=DIAGRAM_TASK,
			)
		)
	return candidates


def _candidate_task_specs(sp_spec) -> list:
	"""
	Inner head task specs eligible as selector candidates, in diagram order.

	Eligibility follows the 2026-07-02 decision: leaf task activities of any
	kind (Script/Service/Send/User/Manual/Business Rule, including
	loop-wrapped variants); containers (embedded Sub-Process, Call Activity,
	nested Ad-hoc Subprocess) and gateways are excluded. Containers are also
	rejected at compile time — the runtime filter is defence in depth.
	"""
	heads = [
		spec
		for spec in sp_spec.start.outputs
		if not isinstance(
			spec, (BpmnStartTask, _EndJoin, SimpleBpmnTask, SubWorkflowTask, MultiChoice)
		)
	]
	diagram_order = list(sp_spec.task_specs)
	heads.sort(key=lambda s: diagram_order.index(s.name))
	return heads


def _registry_candidates(process_model: str | None) -> list:
	# compile_tool_spec ships on WI-001355; resolve lazily so the diagram
	# half of the pool works even where that module isn't installed yet.
	from one_bpmn.agents.tool_registry import compile_tool_spec

	tools = frappe.get_all(
		"AI Agent Tool",
		filters={"is_active": 1},
		fields=["name"],
		order_by="name asc",
	)

	candidates = []
	for row in tools:
		doc = frappe.get_doc("AI Agent Tool", row.name)
		if not _applies_to_process(doc, process_model):
			continue
		candidates.append(ToolCandidate(spec=compile_tool_spec(doc), source=REGISTRY_TOOL))
	return candidates


def _applies_to_process(tool_doc, process_model: str | None) -> bool:
	scoped = [row.process_model for row in (tool_doc.applicable_processes or [])]
	if not scoped:
		return True  # empty = global
	return process_model in scoped
