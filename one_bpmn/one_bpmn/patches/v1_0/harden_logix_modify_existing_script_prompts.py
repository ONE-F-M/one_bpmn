# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""
Ground Logix on the EXISTING script when MODIFYing (stop the "can't retrieve" fabrication).

Symptom: asked to change an existing Server Script, Logix answered
    "Since I can't retrieve the existing script, I'll write a secure version..."
and fabricated a fresh, unrelated script (invented doctypes/variables).

Two causes, both fixed here so `bench migrate` repairs any already-migrated site
(inline_logix_tool_scripts / seed_agent_prompts already ran on existing sites and
won't re-run, so this standalone patch re-applies both changes idempotently):

  1. Writer TOOL prompt only received the linked script's NAME, never its body.
     -> inject `turn["original_script_content"]` into the writer prompt of the two
     writer Server Scripts ("Logix – Tool Write Script", "Logix – Tool Write Agent
     Tool"). Mirrors the source in patches/v1_0/inline_logix_tool_scripts.py
     (WRITE / WRITE_AGENT_TOOL) for fresh installs.

  2. Writer SYSTEM prompt never named the `get_server_script_content` tool nor
     required loading current code on a MODIFY, so the model rationalised past the
     gap. -> prepend a "MODIFY vs CREATE" block to the `script_writer` and
     `tool_writer` sub-prompts that (a) uses the injected body when present,
     (b) REQUIRES calling `get_server_script_content` otherwise, and (c) forbids
     inventing a new script — stop and ask instead.

Idempotent throughout: each change is skipped when its marker is already present,
so re-runs and manual edits are preserved.
"""
import frappe

AGENT_ID = "logix_agent"

# ── 1. writer Server Scripts: inject the existing-script body into the prompt ──
_SCRIPT_OLD = (
	'if current_script:\n'
	'    _parts.append("**Currently linked Server Script:** " + current_script)\n'
	'if _hist:'
)
_SCRIPT_INJECT = (
	'if current_script:\n'
	'    _parts.append("**Currently linked Server Script:** " + current_script)\n'
	'_original = turn.get("original_script_content", "")\n'
	'if _original:\n'
	'    _parts.append("**Existing script (the CURRENT code of the linked Server Script) - you are MODIFYING this. '
	'Rewrite THIS code, preserve its intent and structure, and change only what the user asked. '
	'Do NOT invent a new script from scratch:**\\n```python\\n" + _original + "\\n```")\n'
	'if _hist:'
)
_WRITER_SCRIPTS = ("Logix – Tool Write Script", "Logix – Tool Write Agent Tool")

# ── 2. writer sub-prompts: MODIFY-vs-CREATE guidance ──
_PROMPT_MARKER = "MODIFY vs CREATE (read this FIRST)"
_PROMPT_BLOCK = (
	"\n\n**BEFORE YOU WRITE — MODIFY vs CREATE (read this FIRST):**\n"
	"If you are CHANGING an existing script, you must work from its current code — never write a replacement from scratch.\n"
	"- If your request contains an \"**Existing script**\" block, THAT is the current code. Rewrite it: preserve its intent and structure and change only what the user asked.\n"
	"- If there is no \"Existing script\" block but a \"**Currently linked Server Script:**\" name is given, you MUST first call the `get_server_script_content` tool with that exact name to load the current code, then modify it.\n"
	"- If you cannot obtain the current code (no block, and `get_server_script_content` returns nothing or errors), DO NOT invent a new script. STOP and tell the user in plain English that you could not load the existing script and ask them to confirm how to proceed. NEVER write \"Since I can't retrieve the existing script, I'll write a new one\" and then fabricate one.\n"
)
_PROMPT_TARGETS = ("script_writer", "tool_writer")


def execute():
	# 1. Backfill the two writer Server Scripts.
	for name in _WRITER_SCRIPTS:
		if not frappe.db.exists("Server Script", name):
			continue
		body = frappe.db.get_value("Server Script", name, "script") or ""
		if "original_script_content" in body or body.count(_SCRIPT_OLD) != 1:
			continue  # already injected, or anchor not found (skip rather than corrupt)
		doc = frappe.get_doc("Server Script", name)
		doc.script = body.replace(_SCRIPT_OLD, _SCRIPT_INJECT)
		doc.save(ignore_permissions=True)

	# 2. Harden the writer sub-prompts.
	cfg_name = frappe.db.get_value("AI Agent Configuration", {"agent_id": AGENT_ID}, "name")
	if cfg_name:
		cfg = frappe.get_doc("AI Agent Configuration", cfg_name)
		changed = False
		for row in cfg.sub_prompts:
			if row.sub_agent_id not in _PROMPT_TARGETS:
				continue
			text = row.prompt_text or ""
			if _PROMPT_MARKER in text:
				continue
			nl = text.find("\n")
			row.prompt_text = (text + _PROMPT_BLOCK) if nl == -1 else (text[:nl] + _PROMPT_BLOCK + text[nl:])
			changed = True
		if changed:
			cfg.save(ignore_permissions=True)  # on_update clears agent_config:logix_agent cache

	frappe.db.commit()
