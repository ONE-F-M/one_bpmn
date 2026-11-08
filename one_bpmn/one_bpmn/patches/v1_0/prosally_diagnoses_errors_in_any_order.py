"""ProsAlly diagnoses errors on sites where another ProsAlly patch had already edited the classifier script.

Runs the diagnose edits again with anchors the other patches leave alone, and refreshes the error_diagnoser prompt.
"""

from one_bpmn.one_bpmn.patches.v1_0 import prosally_diagnoses_errors


def execute():
	prosally_diagnoses_errors.execute()
