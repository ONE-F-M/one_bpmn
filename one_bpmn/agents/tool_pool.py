# Copyright (c) 2026, one-fm and contributors
# WI-001353 (2-03) + WI-001423: tool-pool resolution — the ad-hoc sub-process's
# own shapes are the tools. The AI Agent Tool registry was removed in WI-001423
# (both the AI Agent Task and the AI Task Selector are shapes-only now).

from dataclasses import dataclass

from SpiffWorkflow.bpmn.specs.control import BpmnStartTask, SimpleBpmnTask, _EndJoin
from SpiffWorkflow.bpmn.specs.mixins.subworkflow_task import SubWorkflowTask
from SpiffWorkflow.specs import MultiChoice


from one_bpmn.agents.llm_provider.base import ToolSpec
from one_bpmn.api.skill_tools import get_skill_tools


DIAGRAM_TASK = "diagram_task"


@dataclass
class ToolCandidate:
	"""One selector candidate: a ToolSpec plus where it came from.

	spec is the exact shape the agents/llm_provider tool-calling loops consume
	(name, description, parameters, required); source is DIAGRAM_TASK — the only
	source now that the registry is gone.
	"""

	spec: ToolSpec
	source: str


def resolve_tool_pool(subworkflow, task_cfg: dict = None, process_model: str | None = None, instance=None) -> list:
	"""
	Build the candidate list an AI Task Selector chooses from: the ad-hoc
	sub-process's own inner head shapes, in diagram order. Each shape's
	documentation doubles as its tool description (Camunda's model).

	The AI Agent Tool registry was removed (WI-001423) — tools are the shapes.
	``task_cfg`` and ``process_model`` are retained for signature compatibility.

	Returns:
	    list[ToolCandidate]
	"""
	candidates = _diagram_candidates(subworkflow)
	
	if task_cfg and task_cfg.get("aiAgentConfig"):
		import frappe
		agent_id = frappe.db.get_value("AI Agent Configuration", task_cfg["aiAgentConfig"], "agent_id")
		agent_name = task_cfg["aiAgentConfig"]
		has_skills = frappe.db.count("AI Agent Enabled Skill", {"parent": task_cfg["aiAgentConfig"]}) > 0
		if has_skills:
			for spec in get_skill_tools(agent_name, instance):
				candidates.append(ToolCandidate(spec=spec, source="PYTHON_FUNCTION"))
				
	return candidates



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
	kind (Script/Service/Send/User/Manual/Business Rule, including loop-wrapped
	variants); containers (embedded Sub-Process, Call Activity, nested Ad-hoc
	Subprocess) and gateways are excluded. Containers are also rejected at
	compile time — the runtime filter is defence in depth.
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
