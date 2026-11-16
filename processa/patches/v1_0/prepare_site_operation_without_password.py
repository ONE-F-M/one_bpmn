"""prepare_site no longer takes a password: Processa derives it at dispatch. Sites that already ran the first patch get the record rewritten."""

import frappe

from processa.patches.v1_0.add_agent_sandbox_test_site_operations import CONNECTOR, OPERATIONS
from processa.processa_connectors.seed import import_operation


def execute():
	if not frappe.db.exists("BPMN Connector", CONNECTOR):
		return
	for idx, operation in enumerate(OPERATIONS, start=3):
		if operation["value"] == "prepare_site":
			import_operation(CONNECTOR, operation, idx, overwrite=True)
