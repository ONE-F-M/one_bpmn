"""
Dev Agent Write A2A Result never set A2A Task.state to a terminal value — it
only wrote result/status_message. Every prior test's caller happened to be
woken through a different path entirely (dev_agent_callback.py's own direct
_resume_waiting_agent call, fired when the SANDBOX calls back), so this went
undetected all session: nothing before now had an outer caller depending on
poll_a2a_tasks' scheduled reconciler, which is the ONLY thing that wakes a
caller waiting on a "working" A2A Task, and it gates strictly on
`task.state in terminal` (tasks.py:727/754) — status_message is not part of
that check at all.

Confirmed live: A2A-91652 sat at state="working", status_message="done"
indefinitely — Orchestrator Agent's own suspended AI Agent Run (nm5dl309rc),
waiting on it via caller_agent_run, was never woken, and the whole
Work Item -> Software Development v3 -> Orchestrator chain stayed stuck.

Fix: set state="completed" alongside the existing result/status_message
write, so poll_a2a_tasks' reconciler (which runs on a short, flat interval —
see tasks.py's own "Local work is cheap to check" comment) picks it up and
wakes whichever caller is actually waiting, exactly as it already does for
every other local agent's A2A Task completion.
"""

import frappe

_SCRIPT_NAME = "Dev Agent Write A2A Result"

_BODY = """# Writes the Dev Agent's own final report (its plain-text answer after
# calling dispatch_to_sandbox, or after deciding not to) back onto the
# triggering A2A Task. dev_agent_result is the ai_agent step's own
# aiOutputVariable — engine-injected here via task_data's spread into
# locals, same as every other Server Script.
text = (dev_agent_result or "").strip() or "The Dev Agent finished but produced no report."

frappe.db.set_value(
    "A2A Task",
    context_docname,
    {
        "result": frappe.as_json({"text": text}),
        "status_message": "done",
        # Required for poll_a2a_tasks' reconciler to ever wake a waiting
        # caller — it gates strictly on task.state reaching a terminal
        # value (tasks.py), never on status_message. Leaving this unset
        # let A2A-91652 sit at state="working" forever with a caller
        # (Orchestrator Agent) suspended and never resumed.
        "state": "completed",
    },
)
"""


def execute():
	if not frappe.db.exists("Server Script", _SCRIPT_NAME):
		return
	doc = frappe.get_doc("Server Script", _SCRIPT_NAME)
	if (doc.script or "").strip() == _BODY.strip():
		return
	doc.script = _BODY
	doc.save(ignore_permissions=True)
