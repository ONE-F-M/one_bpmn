# Copyright (c) 2026, one-fm and contributors
"""BPMN and DMN parsing, called once when a diagram is saved."""

import io
import uuid

from SpiffWorkflow.bpmn.parser.ProcessParser import AdHocParser
from SpiffWorkflow.bpmn.parser.ValidationException import ValidationException
from SpiffWorkflow.bpmn.specs.bpmn_process_spec import AdHocSubprocessSpec
from SpiffWorkflow.bpmn.workflow import BpmnWorkflow
from SpiffWorkflow.dmn.parser import BpmnDmnParser
from SpiffWorkflow.spiff.parser.task_spec import BusinessRuleTaskParser as SpiffBusinessRuleTaskParser
from SpiffWorkflow.spiff.specs.defaults import BusinessRuleTask as SpiffBusinessRuleTask

from processa.processa_engine.engine.serializer import get_serializer


class _AdHocProcessParser(AdHocParser):
	"""
	AdHocParser that reads standard BPMN attributes the way editors write them.

	BPMN 2.0 declares attributeFormDefault="unqualified", and bpmn-js/Camunda
	write cancelRemainingInstances/ordering without a namespace prefix.
	SpiffWorkflow's NodeParser.attribute() only checks the namespace-qualified
	name, so stock parsing silently ignores both attributes (cancel_remaining
	always defaults to True). Upstream's ordering check is also case-sensitive
	('sequential') while the BPMN enum value is 'Sequential'.
	"""

	def attribute(self, attribute, namespace=None, node=None):
		if namespace is None:
			value = (node if node is not None else self.node).attrib.get(attribute)
			if value is not None:
				return value
		return super().attribute(attribute, namespace=namespace, node=node)

	def create_spec(self):
		if (self.attribute("ordering") or "").lower() == "sequential":
			raise ValidationException(
				"Sequential ordering for ad hoc subprocesses not supported",
				node=self.node,
				file_name=self.filename,
			)
		cancel_remaining = (self.attribute("cancelRemainingInstances") or "true").lower() == "true"
		condition = self.xpath("./bpmn:completionCondition")
		condition = condition[0].text if len(condition) > 0 else None
		return AdHocSubprocessSpec(
			completion_condition=condition,
			cancel_remaining=cancel_remaining,
			name=self.bpmn_id,
			description=self.get_name(),
			filename=self.filename,
		)


# ── DMN (Business Rule Task) support ─────────────────────────
# bpmn-js-spiffworkflow writes <spiffworkflow:calledDecisionId> so we
# use the spiff parser variant (not camunda) for the businessRuleTask.
_BPMN_NS = "http://www.omg.org/spec/BPMN/20100524/MODEL"
_BRT_TAG = f"{{{_BPMN_NS}}}businessRuleTask"

# ─────────────────────────────────────────────────────────────
# Parse  (called once at diagram-save time)
# ─────────────────────────────────────────────────────────────

_SPEC_ID_NAMESPACE = uuid.uuid5(uuid.NAMESPACE_OID, "processa.parse_bpmn")


def _canonicalize_compiled_workflow(wf_dict: dict) -> dict:
	"""
	Make compile output deterministic: same XML in → byte-identical dict out.

	parse_bpmn() wraps the parsed spec in a BpmnWorkflow before serialising,
	which stamps every task with a fresh uuid4 id and a wall-clock
	last_state_change.  Both are instance-level noise at compile time - the
	workflow has never run - so two compiles of an unchanged diagram would
	otherwise differ, defeating change detection on BPMN Process Model saves.

	Task ids are remapped structurally (root/last_task/tasks/subprocesses and
	each task's id/parent/children), never by string substitution, so uuid-like
	text in scripts or task data can never be corrupted.

	Ordering assumption (PR review note): stable ids are assigned in
	first-encounter order over the serialized dict, which follows Python's
	insertion-ordered dicts as built by SpiffWorkflow's serializer from a
	deterministic task-tree traversal. Byte-identity across compiles is
	asserted by tests for the pinned SpiffWorkflow version. If a future
	SpiffWorkflow upgrade changed its serialization iteration order, the
	determinism test would fail loudly and an unchanged diagram would show
	as modified ONCE on its next compile - ids stay internally consistent
	within any single compiled spec, so running instances are unaffected.
	"""
	id_map = {}

	def stable_id(original):
		if original not in id_map:
			id_map[original] = str(uuid.uuid5(_SPEC_ID_NAMESPACE, str(len(id_map))))
		return id_map[original]

	def remap(wf):
		wf["root"] = stable_id(wf["root"])
		if wf.get("last_task") is not None:
			wf["last_task"] = stable_id(wf["last_task"])
		tasks = {}
		for task_id, task in wf.get("tasks", {}).items():
			task["id"] = stable_id(task_id)
			if task.get("parent") is not None:
				task["parent"] = stable_id(task["parent"])
			task["children"] = [stable_id(child) for child in task.get("children", [])]
			task["last_state_change"] = 0.0
			tasks[task["id"]] = task
		wf["tasks"] = tasks
		subprocesses = {}
		for sp_id, sp in wf.get("subprocesses", {}).items():
			remap(sp)
			subprocesses[stable_id(sp_id)] = sp
		wf["subprocesses"] = subprocesses

	remap(wf_dict)
	return wf_dict


def parse_bpmn(
	bpmn_xml: str,
	process_id: str,
	dmn_xml_list: list = None,
	called_xml_list: list = None,
) -> tuple:
	"""
	Parse a BPMN XML string into serialised spec dicts.

	Called ONCE when a diagram is saved/imported - never at runtime.
	Returns two plain dicts that are JSON-safe and ready to store in
	BPMN Process Model.serialized_spec / subprocess_specs.

	When the BPMN diagram contains Business Rule Tasks, the corresponding
	DMN XML strings must be passed via ``dmn_xml_list`` so the parser can
	build DMNEngine instances for each referenced decision table.

	Args:
	    bpmn_xml:      Raw BPMN 2.0 XML string (may contain <?xml …?> declaration)
	    process_id:    The <bpmn:process id="…"> value to use as the entry point
	    dmn_xml_list:  Optional list of DMN XML strings. Each string is a
	                   complete DMN 1.3 document whose <decision id="…"> must
	                   match a calledDecisionId in the BPMN.
	    called_xml_list: Optional list of BPMN XML strings for the processes
	                   this diagram's Call Activities reference. A parser
	                   resolves ``calledElement`` only against processes it has
	                   itself parsed, so a Call Activity pointing at another
	                   Process Model fails with "The process '…' was not found"
	                   unless that model's XML is registered here too. The
	                   caller resolves calledElement → Process Model (see
	                   compiler.called_processes.resolve_called_process_xml); this
	                   function only has to hand the documents to the parser.

	Returns:
	    (spec_dict, sp_specs_dict)

	Raises:
	    ValidationException: if the BPMN or DMN XML is invalid
	    frappe.ValidationError: if process_id not found
	"""
	# Use BpmnDmnParser instead of plain BpmnParser - it extends the base
	# parser with DMN loading/correlation and businessRuleTask support.
	parser = BpmnDmnParser()

	# Register the businessRuleTask parser+spec so SpiffWorkflow knows how
	# to parse <bpmn:businessRuleTask> elements.  Uses the spiff variant
	# because bpmn-js-spiffworkflow writes <spiffworkflow:calledDecisionId>.
	parser.PARSER_CLASSES[_BRT_TAG] = (
		SpiffBusinessRuleTaskParser,
		SpiffBusinessRuleTask,
	)

	# Ad-hoc subprocesses: read cancelRemainingInstances/ordering as the
	# unqualified attributes editors actually write (see _AdHocProcessParser).
	parser.AD_HOC_PARSER_CLASS = _AdHocProcessParser

	# lxml cannot parse a *string* that contains an encoding declaration,
	# but it can parse *bytes*.  Using add_bpmn_io(BytesIO) is the safe path.
	bpmn_bytes = bpmn_xml.strip().encode("utf-8")
	parser.add_bpmn_io(io.BytesIO(bpmn_bytes), filename="diagram.bpmn")

	# Register the called processes BEFORE get_spec(). The parser keeps one
	# namespace of process ids across every document added to it, which is the
	# whole mechanism by which callActivity/calledElement resolves - a process
	# it never parsed does not exist as far as it is concerned.
	for idx, called_xml in enumerate(called_xml_list or []):
		called_str = called_xml.strip() if isinstance(called_xml, str) else ""
		if called_str:
			parser.add_bpmn_io(
				io.BytesIO(called_str.encode("utf-8")), filename=f"called_{idx}.bpmn"
			)

	# Feed each DMN XML string into the parser.  The parser registers each
	# DMN document by its <decision id="…"> attribute, which must match the
	# calledDecisionId written in the BPMN's <spiffworkflow:calledDecisionId>.
	for idx, dmn_xml in enumerate(dmn_xml_list or []):
		dmn_str = dmn_xml.strip() if isinstance(dmn_xml, str) else ""
		if dmn_str:
			parser.add_dmn_str(dmn_str.encode("utf-8"), filename=f"decision_{idx}.dmn")

	try:
		spec = parser.get_spec(process_id)
		sp_specs = parser.get_subprocess_specs(process_id)
	except ValidationException as exc:
		# Reset parser state so it can be reused without contamination
		parser.process_parsers = {}
		raise exc

	# BpmnWorkflowSerializer.to_dict() in SpiffWorkflow 3.x returns an
	# intermediate representation that still contains raw Python objects
	# (e.g. ServiceTask, UserTask) - json.dumps() fails on those.
	#
	# The correct pattern for 3.x is:
	#   serialize_json()  - uses the serializer's custom json_encoder_cls
	#                       to produce a fully encoded JSON *string*
	#   json.loads()      - converts that string back to a plain Python dict
	#                       so it can be stored safely with json.dumps() later
	import json as _json

	serializer = get_serializer()
	wf = BpmnWorkflow(spec, sp_specs)
	wf_dict = _json.loads(serializer.serialize_json(wf))  # clean, JSON-safe dict

	# The second element is EMPTY ON PURPOSE, and it is not a dropped result:
	# BpmnWorkflow(spec, sp_specs) folds the subprocess specs into the workflow,
	# so they are already inside wf_dict["subprocess_specs"] and survive both the
	# serializer and _canonicalize_compiled_workflow. create_workflow() rebuilds
	# from that dict alone and ignores the stored subprocess_specs field (see its
	# docstring). Returning sp_specs here as well would store the same specs
	# twice and let the two copies drift.
	return _canonicalize_compiled_workflow(wf_dict), {}


