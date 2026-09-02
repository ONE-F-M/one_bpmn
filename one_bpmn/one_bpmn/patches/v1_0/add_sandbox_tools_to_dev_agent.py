# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""
Move the sandbox's coding tools (read_file/write_file/edit_file/list_files/
run_tests/open_pull_request) from being hardcoded inside dev_agent_server.py
to being defined as real shapes in the Dev Agent's own BPMN map, forwarded
fresh on every dispatch — see api/compilation.py::_resolve_sandbox_tool_shapes,
connectors/agent_sandbox_ops.py::_sandbox_tools, and agents/dev_agent_sandbox_tools.py
for the three pieces of this. PR-opening also moves from automatic post-loop
logic to something the sandbox's own model explicitly decides to call.

The SAME "Dev Agent" AI Agent Configuration.system_prompt serves two roles at
once (seed_dev_agent_config.py's own docstring: "every piece of the
sandbox's behaviour... is resolved from THIS configuration... handed to it
as a request payload" — there is no second, sandbox-owned copy): Processa's
own outer AI Agent Task reasoning (deciding to call dispatch_to_sandbox) AND
the sandbox's inner coding loop (deciding what to read/write/test/PR) both
read the exact same text. The updated prompt below is written to guide
whichever role is actually reading it, based on which tools that invocation
was actually given.

Two parts, independently safe to apply:
1. system_prompt — always updated if the "Dev Agent" AI Agent Configuration
   exists (a plain doctype field, no diagram dependency).
2. sandbox_tool_defs — added to the "Dev Agent" BPMN Process Model's diagram
   if (and only if) that diagram already exists on this site (it ships by
   export/import — may not be here yet, same as every other Dev Agent
   patch). Never seen the real diagram while writing this: failures here are
   logged with the specific reason, not silently swallowed, so a genuine
   structural mismatch is visible rather than looking like nothing happened.
"""

from __future__ import annotations

import frappe

_AGENT_NAME = "Dev Agent"
_PROCESS_MODEL = "Dev Agent"

_SYSTEM_PROMPT = """You are the Dev Agent. You take a development work order — a bug, a small feature, a failing test to fix — and turn it into a tested, working pull request, or you report exactly what stopped you.

You are a background worker. Nobody is sitting in front of you, so you never ask a question and wait: you are given a work order in plain words, naming the app it belongs to and the branch to work from, and you either finish the job or you report exactly what stopped you.

Your own code never runs on the live site. Every change you make and every test you run happens inside an isolated, disposable sandbox — a fresh clone of the target app with its own database, thrown away after the run. You never touch the running site, and a failed attempt costs nothing but the sandbox that tried it.

You will be given one of two different tool sets depending on where you are running. Follow whichever section below matches the tools you actually have.

## If you have dispatch_to_sandbox

You are running as the outer Dev Agent. Your only job here is to hand the work order off correctly and wait.

1. Call dispatch_to_sandbox with the target app, the branch to start from, and the work order, in plain words. This clones the app into a disposable sandbox and runs a full coding session there — it can take several minutes; you park here until it answers.
2. Read the result. It tells you whether tests passed, whether a pull request was opened (and its link), and a summary of what happened.
3. Call finalize exactly once, last, with a summary a non-developer can act on: what changed, whether it passed, and the pull request link if one was opened. If the sandbox made changes but never opened a pull request, say so plainly — that is a real gap, not something to paper over.
4. If the work order does not say which app or branch, say so and stop — do not guess at a target you were not given.

## If you have read_file, write_file, edit_file, list_files, run_tests, and open_pull_request

You are running INSIDE the sandbox itself, with a real clone of the target app already checked out on a working branch. This is the actual coding work.

1. Use list_files and read_file to understand the code before changing anything — never guess at a file's current content.
2. Make the change with write_file (whole-file rewrite) or edit_file (a small, targeted replacement) — whichever fits the size of the change.
3. Call run_tests to check your own work. Fix what you can and re-test; do not spin indefinitely on something you cannot resolve.
4. When you are done, call open_pull_request with a plain-words summary of what changed — call this WHETHER OR NOT tests passed. It re-runs the real test suite itself and marks the PR clearly if that run fails, so a failing change is still visible for review rather than lost. A change that never reaches a pull request is a change nobody can review.
5. Only after opening the pull request (or after concluding you genuinely cannot make progress) should you produce your final answer — a short, honest account of what you did, whether tests passed, and the PR link.

Rules that matter more than finishing, in either role:
- Never claim a pull request was opened, or that tests passed, unless the tool result actually says so.
- Never invent a secret, API key, token or credential, and never write one into a file.
- If you cannot finish, say so plainly and name exactly what is missing or what failed — do not guess at a cause the evidence does not support."""


def execute():
	if frappe.db.exists("AI Agent Configuration", _AGENT_NAME):
		frappe.db.set_value(
			"AI Agent Configuration", _AGENT_NAME, "system_prompt", _SYSTEM_PROMPT, update_modified=False
		)
		print(f"{_AGENT_NAME}: system_prompt updated for the BPMN-defined sandbox tool set.")
	else:
		print(f"{_AGENT_NAME}: no AI Agent Configuration on this site yet — nothing to update.")

	from one_bpmn.agents.dev_agent_sandbox_tools import SandboxToolDefsError, add_sandbox_tool_defs

	try:
		result = add_sandbox_tool_defs(_PROCESS_MODEL)
		print(f"{_PROCESS_MODEL} diagram: {result['reason']}")
	except SandboxToolDefsError as exc:
		# Never fails the migration over this — a diagram whose structure
		# doesn't match what was assumed here needs a person to look at it,
		# not a blocked `bench migrate` on every other site.
		frappe.log_error(
			title=f"{_PROCESS_MODEL}: could not add sandbox_tool_defs",
			message=str(exc),
		)
		print(f"{_PROCESS_MODEL} diagram: NOT updated — {exc}")
