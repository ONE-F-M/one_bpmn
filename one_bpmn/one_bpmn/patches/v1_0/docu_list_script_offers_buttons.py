"""Docu's list script stage shows Yes and No buttons under a drafted script.

The stage script is refreshed from docu_writes_list_view_scripts, whose edits are idempotent.
"""

from one_bpmn.one_bpmn.patches.v1_0 import docu_writes_list_view_scripts


def execute():
	docu_writes_list_view_scripts.execute()
