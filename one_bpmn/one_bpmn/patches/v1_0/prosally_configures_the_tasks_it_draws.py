# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""
Teach ProsAlly to configure the Service and User Tasks it draws.

A generated diagram arrived with correctly named tasks and nothing else on them,
so every Service Task had to be opened and configured by hand. Two things caused
that, and this patch fixes the first.

The generator prompt defined serviceTask as "the system calls an OUTSIDE service
(another company's system or platform) — payment processor, SMS gateway", and
gave "create/update a database record, send email" to scriptTask. On this
platform a Service Task is the opposite: it is the Frappe operation shape, and
"move the Visa Request to Pending GRD Manager Approval" is precisely what it is
for. The model was being instructed to pick scriptTask for the very steps that
carry configuration, so a configured Service Task was close to unreachable.

The prompt now says what a Service Task is here, names all six Service Types
with their real attribute names, and carries the userTask assignment block
(mode, the field matching that mode, and task actions with their confirm and
signature flags). Values are written using the attribute names the properties
panel reads, so there is no translation layer to drift.

The compiler half lives in the branch: agents/bpmn_task_config.py resolves a
node's "config" into spiffworkflow attributes and derives docStatus and
onlyAllowEdit from the Workflow record, and spiff/pipeline.mjs writes them.

Idempotent and marker-guarded: each edit fires only while its old anchor is
present and the new text is not, so a re-run or a later hand-edit is a no-op.
doc.save() clears the agent_config cache.
"""

import frappe

AGENT_ID = "prosally_agent"
SUB_AGENT = "process_generator"

OLD_SERVICE = """serviceTask     — the system calls an OUTSIDE service (another company's system or platform)
  Business situations: payment processor, SMS gateway, government/regulatory system,
  external ERP, CRM, or third-party API
  Examples: "Process payment via Stripe", "Send OTP via SMS gateway"
"""

NEW_SERVICE = """serviceTask     — a PLATFORM OPERATION the system performs on a Frappe document.
  This is the workhorse type, not a rare one. Use it whenever the step moves a
  document through its workflow, writes a field, or sends a notification:
  changing workflow state, updating a field, emailing, Google Chat, push
  notification, or a configured connector.
  Examples: "Set the Visa Request to Pending GRD Manager Approval",
            "Email the recruiter", "Mark the request Completed"
  A serviceTask SHOULD carry a "config" object — see TASK CONFIGURATION below.
  Prefer serviceTask over scriptTask for any of the six operations listed there;
  scriptTask is only for logic none of them covers.
"""

OLD_SCRIPT = """scriptTask      — the SYSTEM runs automatically (no person involved, no waiting)
  Business situations: check validity (does stock exist? is balance enough?),
  calculate a value (total, tax, score), create/update/read a database record,
  send email or notification, run business rules or validation
  Examples: "System checks leave balance", "Calculate order total", "Send approval email"
"""

NEW_SCRIPT = """scriptTask      — the SYSTEM computes something (no person involved, no waiting)
  Business situations: check validity (does stock exist? is balance enough?),
  calculate a value (total, tax, score), run business rules or validation.
  Examples: "System checks leave balance", "Calculate order total"
  NOT for changing workflow state, writing a field, or sending a message —
  those are serviceTask, and they carry configuration a scriptTask cannot.
"""

OLD_SCHEMA = """      "lane": "lane_id — REQUIRED on every node when lanes are present"
    }"""

NEW_SCHEMA = """      "lane": "lane_id — REQUIRED on every node when lanes are present",
      "config": { "…": "serviceTask / userTask settings — see TASK CONFIGURATION" }
    }"""

OLD_CHECK = """  ✓ No node type is "task\""""

NEW_CHECK = """  ✓ No node type is "task"
  ✓ Every serviceTask has a "config" with a valid "serviceType"
  ✓ Every state-change step is a serviceTask (apply_workflow), never a scriptTask
  ✓ Every userTask the request describes an assignee or buttons for has a "config\""""

LANE_STEP_MARKER = "=== STEP 2 — ASSIGN EVERY NODE TO A LANE ==="

CONFIG_BLOCK = """=== TASK CONFIGURATION — FILL IT IN, DO NOT LEAVE IT FOR THE HUMAN ===

A serviceTask or userTask may carry a "config" object. Everything in the
person's request that names a DocType, a workflow state, an assignee or an
action belongs in it. A task generated without config has to be configured by
hand afterwards, which is the thing this is here to prevent.

Use the key names exactly as written below. Only include a key when the request
actually tells you its value — invent nothing.

--- serviceTask config ---
"serviceType" is required and is exactly one of:

  apply_workflow     move a document to a workflow state
    "serviceTargetDoctype"  the DocType, e.g. "Visa Request"
    "workflowState"         the state to move to, e.g. "Pending GRD Manager Approval"
    Do NOT supply docStatus or onlyAllowEdit. They are read off the workflow
    automatically and anything you write is replaced.

  send_email         email notification
    "emailSubject", "emailBody", "emailTo" (comma-separated addresses),
    "emailToRoles", "emailToDocFields", "emailCc", "emailBcc", "emailAccount",
    "emailUseDoctype" (true/false), "emailDoctype"

  update_field       write a value onto a document
    "updateFieldDoctype", "updateFieldRows"

  google_chat        Google Chat message
    "gchatType" ("individual" or "space"), "gchatEmail" (individual),
    "gchatSpaceId" (space), "gchatMessage"

  push_notification  mobile push
    "pushDoctype", "pushTitle", "pushMessage",
    "pushToUsers", "pushToRoles", "pushToDocFields"

  connector          a configured external connector
    "connectorId", "connectorParams"

--- userTask config ---
  "targetDoctype"    the DocType the person works on, e.g. "Visa Request"
  "assigneeMode"     exactly one of: "User", "DocField", "Round Robin",
                     "Load Balancing", "Table Field"
  then the field that matches the mode:
    "User"        -> "assigneeUser"       (a user id)
    "DocField"    -> "assigneeDocfield"   (a fieldname holding a user)
    "Table Field" -> "assigneeTableField" plus "assigneeTableUserField"
  "taskActions"      the buttons the person gets, as a list. Each entry is
                     either a plain name or an object:
                       {"action": "Approve",
                        "confirmTransition": true,        (ask "are you sure?")
                        "requireDigitalSignature": true}  (require a signature)
                     Use the confirm and signature flags on approvals,
                     rejections, and anything else irreversible.

EXAMPLE — a configured pair:

  {
    "id": "task_grd_review", "type": "userTask", "name": "Review Visa Request",
    "lane": "grd_manager",
    "config": {
      "targetDoctype": "Visa Request",
      "assigneeMode": "DocField",
      "assigneeDocfield": "grd_manager",
      "taskActions": [
        {"action": "Approve", "confirmTransition": true, "requireDigitalSignature": true},
        {"action": "Reject",  "confirmTransition": true}
      ]
    }
  },
  {
    "id": "task_send_grd", "type": "serviceTask", "name": "Send for GRD Approval",
    "lane": "grd_manager",
    "config": {
      "serviceType": "apply_workflow",
      "serviceTargetDoctype": "Visa Request",
      "workflowState": "Pending GRD Manager Approval"
    }
  }

If a workflow state you used does not exist, you will be told which states the
DocType really has — use one of those, do not invent a near-match.

"""


def execute():
	name = frappe.db.get_value("AI Agent Configuration", {"agent_id": AGENT_ID}, "name")
	if not name:
		return
	doc = frappe.get_doc("AI Agent Configuration", name)
	row = next(
		(r for r in (doc.sub_prompts or []) if (r.sub_agent_id or "") == SUB_AGENT), None
	)
	if not row:
		print(f"{AGENT_ID}: no {SUB_AGENT} sub-prompt to update")
		return

	text = row.prompt_text or ""
	before = text

	for old, new in (
		(OLD_SERVICE, NEW_SERVICE),
		(OLD_SCRIPT, NEW_SCRIPT),
		(OLD_SCHEMA, NEW_SCHEMA),
		(OLD_CHECK, NEW_CHECK),
	):
		if new not in text and old in text:
			text = text.replace(old, new, 1)

	if "=== TASK CONFIGURATION" not in text and LANE_STEP_MARKER in text:
		text = text.replace(LANE_STEP_MARKER, CONFIG_BLOCK + LANE_STEP_MARKER, 1)

	if text == before:
		print(f"{AGENT_ID}: {SUB_AGENT} already current")
		return

	row.prompt_text = text
	doc.flags.ignore_validate_update_after_submit = True
	doc.save(ignore_permissions=True)
	print(f"{AGENT_ID}: {SUB_AGENT} now configures tasks ({len(before)} -> {len(text)} chars)")
