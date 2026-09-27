# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""Give the Connector suite the trajectory case it was meant to have.

``add_tool_call_cases_to_agent_suites`` was listed before
``seed_connector_agent_eval_suite``. On a site migrating in that order the
Connector suite did not exist yet when the case patch ran, so it skipped the
suite without a word, was logged as applied, and never came back — the
Orchestrator got its trajectory case and the Connector did not. The BA site
migrated exactly that way.

The order in patches.txt is corrected for sites still to come. This patch is
for the ones already past it: it runs the same code again now the suite is
there. Idempotent by the original's own matching, so a site that already has
the case is untouched.
"""

from one_bpmn.one_bpmn.patches.v1_0.add_tool_call_cases_to_agent_suites import execute as _add_tool_call_cases


def execute():
	_add_tool_call_cases()
