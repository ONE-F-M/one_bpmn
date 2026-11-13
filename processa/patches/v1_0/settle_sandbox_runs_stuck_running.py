"""Settles the sandbox runs that have been open past the deadline and wakes the agents waiting on them."""

from processa.agents_sandbox.sandbox.reaper import settle_overdue


def execute():
	settle_overdue()
