# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""
Teach Logix the sanctioned outbound-HTTP path.

Symptom: when a Logix-generated script needed to call an external service, the
model reached for `import requests` (or urllib/http/socket) — its only related
rule was "No external libraries beyond a standard Frappe installation", with no
positive guidance. The Processa script-security validator
(one_bpmn/security/script_validator.py) lists all of those in FORBIDDEN_MODULES,
so the script was rejected on save: a dead end for "call this API and use the
result" requests.

This patch adds the positive path. Frappe exposes safe HTTP helpers —
`frappe.integrations.utils.make_get_request` / `make_post_request` /
`make_put_request` — which the validator permits (attribute access, no banned
import) and which work in the BPMN engine runtime.

Critical runtime detail (handled in engine.py, not here): BPMN Script Tasks run
through FrappeScriptEngine._run_frappe_server_script using plain exec(), NOT
frappe.safe_exec(). safe_exec pre-binds the BARE names (make_get_request, ...);
plain exec does not. So the contract MUST instruct the FULLY-QUALIFIED
`frappe.integrations.utils.make_get_request(...)` form — the bare-name form would
raise NameError at runtime. `frappe.integrations` is not in the validator's
banned/soft-banned attribute sets, so the qualified form passes the gate.

Three idempotent, marker-guarded sub-prompt edits on the Logix AI Agent
Configuration:
  - script_writer: carve the safe helpers out of the "no external libraries"
    rule, plus a two-example block (a GET, and a POST-with-JSON-body reading a
    secret from settings).
  - script_reviewer: a MUST-fix hard rule — flag any requests/urllib/http/socket
    usage, set approved=false, and return a revised_script that swaps to the safe
    helper preserving behaviour.
  - tool_writer: the same guidance for parity (agent tools share the runtime).

Runs AFTER harden_logix_permission_bypass_prompts (the last patch to touch these
rows on fresh installs). Idempotent: each edit fires only when its old anchor is
still present and the new text is not, so re-runs and manual re-edits are no-ops.
The security ban in script_validator.py is untouched — this only adds the
sanctioned alternative. doc.save() clears the agent_config:logix_agent cache.
"""
import frappe

AGENT_ID = "logix_agent"

# Present in every patched row once applied — the "already done" signal per row.
_MARKER = "frappe.integrations.utils.make_get_request"


# ── script_writer ────────────────────────────────────────────────────────────
# 1) Carve the safe helpers out of the "no external libraries" rule (rule 4 in
#    the dual-contract writer).
WRITER_RULE_OLD = "4. No external libraries beyond a standard Frappe installation."
WRITER_RULE_NEW = (
	"4. No external libraries beyond a standard Frappe installation. "
	"**The ONLY carve-out is outbound HTTP calls.** NEVER `import requests`, `urllib`, "
	"`urllib3`, `http`, or `socket` — the security gate blocks them and the script is "
	"rejected on save. When the script must call an external service, use Frappe's "
	"approved helpers by their FULLY-QUALIFIED name: "
	"`frappe.integrations.utils.make_get_request(url, ...)`, "
	"`frappe.integrations.utils.make_post_request(url, ...)`, or "
	"`frappe.integrations.utils.make_put_request(url, ...)`. Always write the full "
	"`frappe.integrations.utils.` prefix — the bare `make_get_request` name is NOT "
	"defined in this runtime and raises NameError. Read any secret (API key, token) "
	"from a Frappe Settings/Single DocType or site config; never hardcode it and never "
	"log it."
)

# 2) A concrete two-example block, inserted just before the writing-rules list.
WRITER_EXAMPLES_ANCHOR = "**Script writing rules (both contracts):**"
WRITER_EXAMPLES_NEW = (
	"**Calling an external service — use the safe helpers (worked examples):**\n"
	"When the request needs data from — or must send data to — an outside system, call "
	"Frappe's sanctioned HTTP helpers by their fully-qualified name. NEVER "
	"`import requests`/`urllib`/`http`/`socket` (the security gate rejects them). Each "
	"helper returns the parsed JSON body when the response is JSON.\n\n"
	"GET (with query params):\n"
	"```python\n"
	"# Look up the current USD exchange rate from an external service.\n"
	"response = frappe.integrations.utils.make_get_request(\n"
	'    "https://api.example.com/rates",\n'
	'    params={"base": "USD"},\n'
	")\n"
	'result["usd_rate"] = response.get("rate")\n'
	"```\n\n"
	"POST with a JSON body, authenticating with a secret read from settings (never "
	"hardcoded, never logged):\n"
	"```python\n"
	"# Notify an external service that this process finished.\n"
	'api_key = frappe.db.get_single_value("My Integration Settings", "api_key")\n'
	"frappe.integrations.utils.make_post_request(\n"
	'    "https://api.example.com/notify",\n'
	'    headers={"Authorization": f"Bearer {api_key}"},\n'
	'    json={"process": doc.name, "status": "done"},\n'
	")\n"
	'result["notified"] = True\n'
	"```\n\n"
	"Read every secret from a Settings/Single DocType (or site config) — never hardcode "
	"it and never write it to a log.\n\n"
	"**Script writing rules (both contracts):**"
)


# ── script_reviewer ──────────────────────────────────────────────────────────
# Prepend a MUST-fix hard rule just before the evaluation checklist.
REVIEWER_ANCHOR = "Evaluate the given Python server script for:"
REVIEWER_NEW = (
	"**HARD RULE — outbound HTTP must use the sanctioned helpers (either kind):**\n"
	"`requests`, `urllib`, `urllib3`, `http`, and `socket` are ALL blocked by the "
	"security gate — a script importing or using any of them is rejected on save. If "
	"the draft makes a network call via any of these (e.g. `import requests` / "
	"`requests.get` / `urllib.request.urlopen` / `http.client`), you MUST set "
	"approved=false and return a revised_script that performs the SAME call through "
	"Frappe's approved helpers, fully qualified:\n"
	"- `frappe.integrations.utils.make_get_request(url, headers=..., params=...)`\n"
	"- `frappe.integrations.utils.make_post_request(url, headers=..., json=..., data=...)`\n"
	"- `frappe.integrations.utils.make_put_request(url, ...)`\n"
	"Preserve the original behaviour exactly — same URL, headers, query params, "
	"JSON/body payload, and timeout. Keep the full `frappe.integrations.utils.` prefix "
	"(the bare helper name is undefined at runtime → NameError). Move any hardcoded API "
	"key/token/secret to a read from a Settings/Single DocType or site config, and never "
	"log it.\n\n"
	"Evaluate the given Python server script for:"
)


# ── tool_writer ──────────────────────────────────────────────────────────────
# Append an HTTP constraint to the agent-tool HARD CONSTRAINTS list. Agent tools
# must never raise on failure, so the guidance wraps the call and reports via
# result["error"].
TOOL_WRITER_ANCHOR = (
	"4. Security: never use `frappe.set_user`, `frappe.flags.ignore_permissions`, "
	"exec/eval, os/sys/subprocess imports, or destructive raw SQL — the security gate "
	"rejects the script."
)
TOOL_WRITER_NEW = (
	TOOL_WRITER_ANCHOR + "\n"
	"5. Outbound HTTP: NEVER `import requests`/`urllib`/`http`/`socket` (the security "
	"gate blocks them). To call an external service use the FULLY-QUALIFIED helpers "
	"`frappe.integrations.utils.make_get_request(url, ...)`, "
	"`frappe.integrations.utils.make_post_request(url, json=..., headers=...)`, or "
	"`frappe.integrations.utils.make_put_request(...)`. Keep the full "
	"`frappe.integrations.utils.` prefix — the bare name is undefined here (NameError). "
	"Read any secret from a Settings/Single DocType or site config; never hardcode or "
	"log it. Because an agent tool must NOT raise on failure, wrap the call in "
	"try/except and report problems via `result[\"error\"] = \"...\"`."
)


# (sub_agent_id, old_anchor, new_text). Each entry is independently idempotent.
_REPLACEMENTS = (
	("script_writer", WRITER_RULE_OLD, WRITER_RULE_NEW),
	("script_writer", WRITER_EXAMPLES_ANCHOR, WRITER_EXAMPLES_NEW),
	("script_reviewer", REVIEWER_ANCHOR, REVIEWER_NEW),
	("tool_writer", TOOL_WRITER_ANCHOR, TOOL_WRITER_NEW),
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

	# Observability: a row that is not yet patched (marker absent) but whose
	# anchors were not found means the prompt diverged from the expected layout —
	# worth a heads-up rather than a silent skip.
	for row in doc.sub_prompts:
		if row.sub_agent_id not in {"script_writer", "script_reviewer", "tool_writer"}:
			continue
		text = row.prompt_text or ""
		if _MARKER not in text and row.sub_agent_id not in touched_rows:
			frappe.log_error(
				title="add_logix_http_helper_guidance: anchor not found",
				message=(
					f"Sub-prompt '{row.sub_agent_id}' on the Logix agent config did not "
					"contain the expected anchor(s); HTTP-helper guidance was not added. "
					"Add it manually or verify the prompt text."
				),
			)

	if updated:
		doc.save(ignore_permissions=True)  # on_update clears agent_config:logix_agent cache
		frappe.db.commit()
