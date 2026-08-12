"""Backward-compatible re-export of ``one_bpmn.api.bpmn_task_actions``.

This module was renamed — its old name suggested a connection to the
Frappe ``ToDo`` doctype that never actually existed; the code is
doctype-agnostic. This shim only exists so that any AMP email already
sent before the rename (whose ``action-xhr`` URL has
``one_bpmn.api.todo_actions.handle_amp_action`` baked into its stored
HTML) keeps working. New code should import from
``one_bpmn.api.bpmn_task_actions`` directly — do not add anything new
here.
"""

from __future__ import annotations

from one_bpmn.api.bpmn_task_actions import (
	apply_amp_headers,
	get_amp_task_status,
	handle_amp_action,
)

__all__ = ["apply_amp_headers", "get_amp_task_status", "handle_amp_action"]
