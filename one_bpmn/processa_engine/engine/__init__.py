# Copyright (c) 2026, one-fm and contributors
"""SpiffWorkflow backend engine for one_bpmn.

This package is the only place in Processa Engine that imports SpiffWorkflow;
everything else gets its classes and functions from here.
"""

from SpiffWorkflow.bpmn.specs.bpmn_process_spec import AdHocSubprocessSpec
from SpiffWorkflow.bpmn.specs.defaults import SendTask
from SpiffWorkflow.bpmn.specs.event_definitions.timer import TimerEventDefinition
from SpiffWorkflow.bpmn.specs.mixins import CallActivityMixin
from SpiffWorkflow.bpmn.specs.mixins.multiinstance_task import MultiInstanceTask
from SpiffWorkflow.bpmn.specs.mixins.subworkflow_task import SubWorkflowTask
from SpiffWorkflow.util.task import TaskState

from one_bpmn.processa_engine.engine import spiff_patches
from one_bpmn.processa_engine.engine.adhoc import (
	NO_ACTIVATION,
	_adhoc_completion_met,
	_adhoc_subworkflows,
	_gate_adhoc_subworkflow,
	adhoc_head_tasks,
	adhoc_pending_head_tasks,
	do_engine_steps_gated,
	notify_adhoc_activation,
	select_next_adhoc_task,
)
from one_bpmn.processa_engine.engine.helpers import (
	BUFFERED_MESSAGE_PREFIXES,
	TASK_TYPE_LABELS,
	clean_doc_from_wf_data,
	declares_message,
	get_ready_user_tasks,
	get_task_display_name,
	get_task_type_label,
	json_safe_doc_fields,
	refresh_context_doc,
	send_message,
)
from one_bpmn.processa_engine.engine.parser import parse_bpmn
from one_bpmn.processa_engine.engine.script_engine import (
	FrappeScriptEngine,
	_check_script_permissions,
	_make_script_engine,
)
from one_bpmn.processa_engine.engine.serializer import (
	create_workflow,
	get_serializer,
	restore_workflow,
	serialize_workflow,
)

__all__ = [
	"AdHocSubprocessSpec",
	"SendTask",
	"TimerEventDefinition",
	"CallActivityMixin",
	"MultiInstanceTask",
	"SubWorkflowTask",
	"TaskState",
	"spiff_patches",
	"NO_ACTIVATION",
	"_adhoc_completion_met",
	"_adhoc_subworkflows",
	"_gate_adhoc_subworkflow",
	"adhoc_head_tasks",
	"adhoc_pending_head_tasks",
	"do_engine_steps_gated",
	"notify_adhoc_activation",
	"select_next_adhoc_task",
	"BUFFERED_MESSAGE_PREFIXES",
	"TASK_TYPE_LABELS",
	"clean_doc_from_wf_data",
	"declares_message",
	"get_ready_user_tasks",
	"get_task_display_name",
	"get_task_type_label",
	"json_safe_doc_fields",
	"refresh_context_doc",
	"send_message",
	"parse_bpmn",
	"FrappeScriptEngine",
	"_check_script_permissions",
	"_make_script_engine",
	"create_workflow",
	"get_serializer",
	"restore_workflow",
	"serialize_workflow",
]
