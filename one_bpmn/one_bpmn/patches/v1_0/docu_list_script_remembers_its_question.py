"""Docu's list script stage remembers a question it asked and can write a script that removes the Add button.

The list script writer prompt and the stage script are refreshed from docu_writes_list_view_scripts,
whose edits are idempotent.
"""

from one_bpmn.one_bpmn.patches.v1_0 import docu_writes_list_view_scripts


def execute():
	docu_writes_list_view_scripts.execute()
