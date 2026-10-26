"""Settles the sandbox runs that have been open past the deadline and wakes the agents waiting on them."""

from one_bpmn.one_bpmn.connectors.agent_sandbox_reaper import settle_overdue


def execute():
	settle_overdue()
