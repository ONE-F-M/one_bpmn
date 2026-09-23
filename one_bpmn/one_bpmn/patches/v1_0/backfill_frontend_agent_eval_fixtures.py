"""Backfill A2A Task fixtures for the Frontend Agent's eval suites, on any
site where they're missing.

The four seed patches for these suites (``seed_frontend_agent_eval_suite``,
``..._adversarial_suite``, ``..._trajectory_suite``, ``..._coload_budget_suite``)
are each idempotent and create-or-reuse their own fixtures — but Frappe tracks
patch execution by NAME in ``Patch Log``, not by content: once a patch name is
logged as run on a site, ``bench migrate`` never re-runs it, even after the
file's content changes afterward.

That bit BA: its Patch Log already had ``seed_frontend_agent_eval_suite``
logged from when it only wrote the first 4 cases (2026-09-14). Cases 5-7,
added to that same file later, will never get a fixture via a normal migrate
on that site — the patch that would create them is permanently "done" as far
as migrate is concerned. Separately, this agent's 3 newer suites
(Adversarial, Trajectory, Co-Load Budget) were seeded directly via BA's REST
API with no fixture at all, deliberately (see those patches' own module
docstrings for why a fixture can't be created that way), and their own
patches hadn't run on BA yet either.

This patch's whole job is to re-invoke the four modules' own ``execute()``
functions — no new case-writing logic here, just re-running what's already
proven idempotent, under a NEW patch name Frappe has never logged, so it is
guaranteed to actually run once this reaches a site through the normal deploy
path. On a site where every fixture already resolves (local, having run these
already), every ``execute()`` call is a clean no-op.
"""

from one_bpmn.one_bpmn.patches.v1_0 import (
	seed_frontend_agent_adversarial_suite,
	seed_frontend_agent_coload_budget_suite,
	seed_frontend_agent_eval_suite,
	seed_frontend_agent_trajectory_suite,
)

MODULES = (
	seed_frontend_agent_eval_suite,
	seed_frontend_agent_adversarial_suite,
	seed_frontend_agent_trajectory_suite,
	seed_frontend_agent_coload_budget_suite,
)


def execute():
	for module in MODULES:
		module.execute()
