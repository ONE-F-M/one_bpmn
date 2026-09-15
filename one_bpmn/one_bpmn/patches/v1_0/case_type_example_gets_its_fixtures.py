# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""Re-seed the case-type example so every case has something to run against.

The worked example was seeded before it had fixtures. A site that migrated in
that window — the BA site did, on 14 September — holds seven cases with a
title, a type and assertions, and no document to run them against. Every one
errors with *"Case runs process map 'Connector Agent', so it must name the
document to run against"*, and the seed will not run again because it is
already in the Patch Log.

This runs it again, now that it writes an A2A Task for each case and a memory
spec for the Memory one. The seed matches by title and reuses a task the case
already points at, so a site that is already whole is left alone.
"""

from one_bpmn.one_bpmn.patches.v1_0.seed_connector_case_type_suite import execute as _seed


def execute():
	_seed()
