# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""
Close the `frappe.make_get_request` gap in the Logix HTTP-helper guidance.

Symptom: a Logix-generated script called `frappe.make_get_request(...)` /
`frappe.make_post_request(...)` and crashed at runtime with
`AttributeError: module 'frappe' has no attribute 'make_get_request'`.

Why the earlier patch (add_logix_http_helper_guidance) did not prevent it: that
patch taught the FULLY-QUALIFIED `frappe.integrations.utils.make_get_request`
form and warned only against the BARE `make_get_request` name (which raises
NameError). It never named the third — and most natural — mistake: the
`frappe.`-prefixed form with `.integrations.utils` DROPPED
(`frappe.make_get_request`). The model "knows" the helpers live under `frappe`
and prefixes accordingly, but forgets the submodule segment.

That malformed form defeats BOTH existing defenses:
  * the Processa security validator does NOT block it — it is plain attribute
    access on `frappe`, not a banned import, so the script saves cleanly; and
  * the script_reviewer sub-prompt only flags `requests`/`urllib`/`http`/
    `socket`, so it waves the malformed helper path through.
Result: the script ships silently and only crashes when the BPMN task runs, with
AttributeError (not the NameError the old guidance describes).

This patch names that exact failure in three sub-prompts of the Logix AI Agent
Configuration:
  - script_writer: extend the "no external libraries" rule so `frappe.<helper>`
    (prefix present, `.integrations.utils` missing) is called out as WRONG →
    AttributeError, and stress the path is ALWAYS `frappe.integrations.utils.`.
  - script_reviewer: add the malformed-path form to the HARD RULE so the reviewer
    sets approved=false and restores the prefix — it is the ONLY layer that
    catches this (the gate does not).
  - tool_writer: the same callout for parity (agent tools share the runtime).

Idempotent and marker-guarded: each edit fires only when its old anchor is still
present and the new text is not, so re-runs and manual re-edits are no-ops. Runs
AFTER add_logix_http_helper_guidance (whose text is the anchor here).
doc.save() clears the agent_config:logix_agent cache.
"""
import frappe

AGENT_ID = "logix_agent"

# Present in every patched row once applied — the "already done" signal per row.
_MARKER = "no `make_get_request` attribute on the top-level `frappe` module"


# ── script_writer ────────────────────────────────────────────────────────────
WRITER_OLD = (
	"Always write the full `frappe.integrations.utils.` prefix — the bare "
	"`make_get_request` name is NOT defined in this runtime and raises NameError."
)
WRITER_NEW = (
	WRITER_OLD + " **Just as wrong is `frappe.make_get_request(...)` — the `frappe.` "
	"prefix kept but `.integrations.utils` dropped. There is no `make_get_request` "
	"attribute on the top-level `frappe` module, so it crashes at runtime with "
	"`AttributeError: module 'frappe' has no attribute 'make_get_request'`, and the "
	"security gate does NOT catch it (plain attribute access, not a banned import) — so "
	"it ships silently and only fails when the task runs. The path is ALWAYS exactly "
	"`frappe.integrations.utils.<helper>`; never `frappe.<helper>` and never the bare "
	"name.**"
)


# ── script_reviewer ──────────────────────────────────────────────────────────
REVIEWER_OLD = (
	"Keep the full `frappe.integrations.utils.` prefix (the bare helper name is "
	"undefined at runtime → NameError)."
)
REVIEWER_NEW = (
	REVIEWER_OLD + " ALSO reject the `frappe.<helper>` form with `.integrations.utils` "
	"missing — e.g. `frappe.make_get_request` / `frappe.make_post_request` / "
	"`frappe.make_put_request`: there is no such attribute on the top-level `frappe` "
	"module, so it raises AttributeError at runtime, and because it is plain attribute "
	"access the security gate lets it through — you are the ONLY layer that catches it. "
	"If the draft calls any make_get_request/make_post_request/make_put_request without "
	"the complete `frappe.integrations.utils.` prefix, set approved=false and return a "
	"revised_script with the full prefix restored."
)


# ── tool_writer ──────────────────────────────────────────────────────────────
TOOL_WRITER_OLD = (
	"Keep the full `frappe.integrations.utils.` prefix — the bare name is undefined "
	"here (NameError)."
)
TOOL_WRITER_NEW = (
	TOOL_WRITER_OLD + " Never `frappe.make_get_request(...)` either — prefix kept but "
	"`.integrations.utils` dropped: there is no `make_get_request` attribute on the "
	"top-level `frappe` module, so it raises AttributeError at runtime while sailing "
	"past the security gate. The path is always exactly `frappe.integrations.utils.<helper>`."
)


# (sub_agent_id, old_anchor, new_text). Each entry is independently idempotent.
_REPLACEMENTS = (
	("script_writer", WRITER_OLD, WRITER_NEW),
	("script_reviewer", REVIEWER_OLD, REVIEWER_NEW),
	("tool_writer", TOOL_WRITER_OLD, TOOL_WRITER_NEW),
)


def execute():
	name = frappe.db.get_value("AI Agent Configuration", {"agent_id": AGENT_ID}, "name")
	if not name:
		return

	doc = frappe.get_doc("AI Agent Configuration", name)

	updated = False
	touched_rows = set()
	for row in doc.sub_prompts:
		for sub_agent_id, old, new in _REPLACEMENTS:
			if row.sub_agent_id != sub_agent_id:
				continue
			text = row.prompt_text or ""
			# Idempotent: only act when the old anchor is still present and the
			# new text is not — so re-runs and manual re-edits are preserved.
			if new not in text and old in text:
				row.prompt_text = text.replace(old, new, 1)
				updated = True
				touched_rows.add(sub_agent_id)

	# Observability: a row not yet patched (marker absent) whose anchor was not
	# found means the prompt diverged from the expected layout (e.g.
	# add_logix_http_helper_guidance never applied) — worth a heads-up.
	for row in doc.sub_prompts:
		if row.sub_agent_id not in {"script_writer", "script_reviewer", "tool_writer"}:
			continue
		text = row.prompt_text or ""
		if _MARKER not in text and row.sub_agent_id not in touched_rows:
			frappe.log_error(
				title="fix_logix_http_helper_qualified_path: anchor not found",
				message=(
					f"Sub-prompt '{row.sub_agent_id}' on the Logix agent config did not "
					"contain the expected anchor; the frappe.<helper> AttributeError "
					"guidance was not added. Verify add_logix_http_helper_guidance ran, "
					"or add the note manually."
				),
			)

	if updated:
		doc.save(ignore_permissions=True)  # on_update clears agent_config:logix_agent cache
		frappe.db.commit()
