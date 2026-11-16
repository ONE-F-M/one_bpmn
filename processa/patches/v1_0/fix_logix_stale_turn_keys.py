# Copyright (c) 2026, one-fm and contributors
"""Logix answered its own reviewer instead of the user.

Logix's stage tools became AI Agent Tasks (per-agent migration), so a shape's
output now arrives in the turn as ``<bpmn_id>_result``. Two tool scripts were
left reading the keys the old inline pipeline wrote:

* ``Logix – Tool Review Script`` read ``turn["draft"]`` — never written again —
  so it reviewed an empty string, called every turn a question, and its own
  "please provide the draft Python server script" became the user's reply.
* ``Logix – Tool Finalize`` read ``turn["intent"]`` the same way (so a MODIFY
  finalized as a CREATE, dropping the diff), and refused with "I was unable to
  generate a safe script" whenever no validated code existed — which is also
  what a greeting produces, so "hi" was answered with a security warning.

The replacements are the same ones made to the installer
(``inline_logix_tool_scripts``) for fresh sites. Idempotent: each edit applies
only while its old text is still present.
"""

import frappe

_REVIEW = "Logix – Tool Review Script"
_FINALIZE = "Logix – Tool Finalize"

# (old text, new text, marker). The marker is what proves an edit is already
# applied: the review replacement CONTAINS its own anchor, so matching on the
# anchor alone would nest the block on every run.
_EDITS = {
	_REVIEW: [
		(
			'draft = turn.get("draft", "")',
			'''draft = turn.get("draft", "") or ""
# The writer is an AI Agent Task now, so its draft arrives as the shape's own
# result — `draft` is a key nothing has written since that migration. Reviewing
# the empty string made every turn look like a question, and the reviewer's
# "please provide the draft" reached the user as the answer.
if not draft:
    _wsr = turn.get("write_script_result") or turn.get("write_agent_tool_result") or {}
    if isinstance(_wsr, dict):
        draft = (_wsr.get("write_script_output") or _wsr.get("write_agent_tool_output")
                 or _wsr.get("output") or "")
    elif isinstance(_wsr, str):
        draft = _wsr
if not isinstance(draft, str):
    draft = str(draft or "")''',
			"_wsr = turn.get(\"write_script_result\")",
		),
	],
	_FINALIZE: [
		(
			'    intent = turn.get("intent", "CREATE")',
			'''    intent = turn.get("intent") or ""
    # Same migration: the classifier is an AI Agent Task, so its answer lives in
    # the shape's result. Reading the old key made every turn a CREATE, which
    # silently dropped the diff and the original code on a MODIFY.
    if not intent:
        _cir = turn.get("classify_intent_result") or {}
        _cio = _cir.get("classify_intent_output") if isinstance(_cir, dict) else None
        if isinstance(_cio, dict):
            intent = _cio.get("intent") or ""
    intent = intent or "CREATE"''',
			"_cir = turn.get(\"classify_intent_result\")",
		),
		(
			'''    if not turn.get("script_safe"):
        update_turn(context_docname, output={
            "intent": intent, "response": _REFUSAL, "diff": None,''',
			'''    _final_text = (turn.get("final") or "").strip()
    if not _final_text:
        # The writer is an AI Agent Task, so its text arrives as the shape's own
        # result. Reaching for it here is what lets a turn that answered in prose
        # — a greeting, a question back to the user — keep its reply.
        _wsr = turn.get("write_script_result") or turn.get("write_agent_tool_result") or {}
        if isinstance(_wsr, dict):
            _final_text = (_wsr.get("write_script_output") or _wsr.get("write_agent_tool_output")
                           or _wsr.get("output") or "")
        elif isinstance(_wsr, str):
            _final_text = _wsr
        _final_text = (_final_text or "").strip()
    # The refusal belongs to a script that was written and could not be made
    # safe. Prose has a perfectly good reply, and "unable to generate a safe
    # script" was both wrong and alarming as an answer to "hi". Code that never
    # reached the reviewer still refuses — the security gate lives there, so an
    # unvalidated script must never be published just because prose may pass.
    if not turn.get("script_safe") and (not _final_text or "```python" in _final_text):
        update_turn(context_docname, output={
            "intent": intent, "response": _REFUSAL, "diff": None,''',
			"_final_text = (turn.get(\"final\") or \"\").strip()",
		),
		(
			'''    else:
        final = turn.get("final", "")
        code = turn.get("modified_code", "")''',
			'''    else:
        final = _final_text or turn.get("final", "")
        code = turn.get("modified_code", "")''',
			'final = _final_text or turn.get("final", "")',
		),
	],
}


def execute():
	for name, edits in _EDITS.items():
		if not frappe.db.exists("Server Script", name):
			continue
		script = frappe.db.get_value("Server Script", name, "script") or ""
		updated = script
		for old, new, marker in edits:
			if marker in updated:
				continue  # already applied
			if old in updated:
				updated = updated.replace(old, new, 1)
		if updated != script:
			frappe.db.set_value("Server Script", name, "script", updated, update_modified=False)
			print(f"fix_logix_stale_turn_keys: updated {name}")
