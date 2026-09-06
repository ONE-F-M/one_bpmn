# Copyright (c) 2026, one-fm and contributors
"""LuCrusher paid twice for its own analysis (WI-002195).

Two of its tools put far more into the model's context than the model used.

**The codebase scan** returned twenty fully-detailed rows per list, each list
under two spellings, plus the narrative summary built from the same rows —
76,893 characters (about 19k tokens) on run dbsfvdj6pq, re-read by every later
model call of that turn. The full scan was ALREADY stored in the turn store and
attached to finalize from there; the model never needed the rows. The tool now
returns a digest: the ranked summary, counts, and the top names the model can
act on. The full result still reaches the frontend by the same path as before.

**Confirmations** re-sent the whole draft. When the user said yes to a topology
or a migration plan, the model called finalize with the entire object again —
57,259 characters on run 5gkemvvln0, about 13k completion tokens to say "go
ahead". The map's Save Response script already carries a draft forward on a
confirmation turn when the model omits it; the instruction to omit it is what
was missing. It is added to the agent's system prompt, where it is cached.

Written against the BA site's copies of the script and the configuration
(2026-09-06). Idempotent: each edit is applied only while its anchor is present
and its marker is absent, and re-running changes nothing.

The digest function is self-contained on purpose: the script runs with split
globals/locals, so a top-level ``def`` cannot see other top-level names and
must use only its own arguments.
"""

import frappe

_AGENT_ID = "lucrusher_agent"
_SCAN_SCRIPT = "LuCrusher – Tool Scan Codebase"

# ── 1. the scan tool returns a digest ────────────────────────────────────────

_SCAN_OLD = '''result["codebase_scan"] = _lucrusher_trim_scan(_lcr_full_scan)'''

_SCAN_MARKER = "def _lucrusher_scan_digest(scan):"

_SCAN_NEW = '''def _lucrusher_scan_digest(scan):
    # What the MODEL is shown (WI-002195). The full scan is already in the turn
    # store (update_turn above) and finalize attaches it to the result itself,
    # so the model needs the ranked summary and the names it can act on — not
    # twenty fully-detailed rows per list under two spellings each. Measured:
    # the trimmed structure ran to 76,893 characters on one call.
    if not scan or scan.get("error"):
        return scan

    def _count(key):
        items = scan.get(key) or []
        return len(items) if isinstance(items, list) else 0

    top_doctypes = []
    for dt in (scan.get("matched_doctypes") or [])[:10]:
        if isinstance(dt, dict):
            top_doctypes.append({
                "doctype": dt.get("doctype"),
                "app": dt.get("app"),
                "score": dt.get("score"),
            })
    top_methods = []
    for m in (scan.get("whitelisted_methods") or [])[:10]:
        if isinstance(m, dict):
            top_methods.append({"function": m.get("function"), "file": m.get("file")})

    return {
        "summary": scan.get("summary") or "",
        "counts": {
            "doctypes": _count("matched_doctypes"),
            "hooks": _count("hooks_found"),
            "controllers": _count("controller_classes"),
            "whitelisted_methods": _count("whitelisted_methods"),
        },
        "top_doctypes": top_doctypes,
        "top_whitelisted_methods": top_methods,
        "apps_scanned": scan.get("apps_scanned") or [],
        "note": (
            "This is a digest. The full scan is stored for this turn and attached "
            "to finalize automatically - do not repeat it and do not pass it to finalize."
        ),
        "error": None,
    }


result["codebase_scan"] = _lucrusher_scan_digest(_lcr_full_scan)'''

# ── 2. confirmations send only intent and response ───────────────────────────

_PROMPT_HEADING = "## Confirming a draft"

_PROMPT_BLOCK = (
	"When the user confirms something you proposed — intent TOPOLOGY_CONFIRMED, "
	"MIGRATION_TASKS_CONFIRMED or PROSALLY_PROMPT_CONFIRMED — call finalize with "
	"ONLY intent and response. The platform re-uses the draft it already holds "
	"from the previous turn, so do not send topology, migration_tasks or "
	"prosally_prompts again. If the user asked for a change to the draft, send "
	"only the object that changed. A confirmation reply is short: say what was "
	"confirmed and what happens next."
)


def apply_scan_digest(script: str) -> tuple[str, bool]:
	"""The scan-script edit as a pure function of its text. Returns the new text
	and whether anything changed; applied once, and only where the anchor is."""
	if _SCAN_MARKER in script or _SCAN_OLD not in script:
		return script, False
	return script.replace(_SCAN_OLD, _SCAN_NEW, 1), True


def with_confirmation_block(prompt: str) -> tuple[str, bool]:
	"""The system-prompt edit as a pure function of its text."""
	prompt = prompt or ""
	if _PROMPT_BLOCK in prompt:
		return prompt, False
	if prompt.strip():
		return f"{prompt.rstrip()}\n\n{_PROMPT_HEADING}\n{_PROMPT_BLOCK}\n", True
	return f"{_PROMPT_HEADING}\n{_PROMPT_BLOCK}\n", True


def execute():
	if frappe.db.exists("Server Script", _SCAN_SCRIPT):
		script = frappe.db.get_value("Server Script", _SCAN_SCRIPT, "script") or ""
		updated, changed = apply_scan_digest(script)
		if changed:
			frappe.db.set_value(
				"Server Script", _SCAN_SCRIPT, "script", updated, update_modified=False
			)
			print(f"lucrusher_scan_digest_and_short_confirmations: {_SCAN_SCRIPT} returns a digest")

	name = frappe.db.get_value("AI Agent Configuration", {"agent_id": _AGENT_ID}, "name")
	if name:
		prompt = frappe.db.get_value("AI Agent Configuration", name, "system_prompt") or ""
		updated, changed = with_confirmation_block(prompt)
		if changed:
			frappe.db.set_value(
				"AI Agent Configuration", name, "system_prompt", updated, update_modified=False
			)
			print(f"lucrusher_scan_digest_and_short_confirmations: {name} told to confirm without re-sending drafts")
