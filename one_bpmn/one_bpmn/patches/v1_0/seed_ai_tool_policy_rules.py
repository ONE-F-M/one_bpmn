# Copyright (c) 2026, one-fm and contributors
"""Seed the baseline tool-policy rules (WI-001645).

Rule group 1 of the story: deny the highest-risk targets outright. These are the
four categories the process owner signed off, expressed as protected DocTypes
matched against whatever a tool call passes as an argument.

Scoping decisions worth knowing about:

* **Identity & Permissions** and **Code Execution** apply to EVERY tool. Nothing
  an agent legitimately does needs to touch a Role or a Server Script — except
  Logix, whose entire job is authoring Server Scripts, so it is exempted by name
  on the Code Execution rule. That exemption is the reason the rule can be this
  broad without breaking a live agent.

* **Payroll & Financial** is scoped to `transition_workflow` — the only tool on
  the deployed surface that MUTATES an arbitrary business document. Scoping it
  narrowly keeps HR's legitimate read queries (`get_list`, `query_documents`)
  working. Widen it to all tools when you decide agents should not read payroll
  either; that is a policy call, not an engineering one.

* **Destructive & Bulk** ships DISABLED. Its record-count ceiling needs a number
  nobody has agreed yet, and this story explicitly covers only the rule groups
  that need no thresholds. The row exists so the decision has a home.

Idempotent: a rule that already exists is left alone, so re-running never
overwrites an edit a process owner has made.
"""

import frappe

LOGIX = "logix"  # AI Agent Configuration record name

RULES = [
    {
        "rule_name": "Deny identity and permission changes",
        "category": "Identity & Permissions",
        "action": "Deny",
        "enabled": 1,
        "restricted_doctypes": "\n".join([
            "User", "Role", "Has Role", "Role Profile",
            "Custom DocPerm", "DocPerm", "User Permission", "User Type",
        ]),
        "restricted_tools": "",
        "violation_message": (
            "changing users, roles or permissions is not something an agent may do. "
            "A person with the right access has to make this change."
        ),
        "exempt_agents": [],
    },
    {
        "rule_name": "Deny changes to executable code",
        "category": "Code Execution",
        "action": "Deny",
        "enabled": 1,
        "restricted_doctypes": "\n".join([
            "Server Script", "Client Script", "Scheduled Job Type", "Custom Script",
        ]),
        "restricted_tools": "",
        "violation_message": (
            "creating or changing code that runs on the server is not something an "
            "agent may do outside the script-authoring workflow."
        ),
        # Logix authors Server Scripts for a living; without this exemption the
        # rule would disable the agent entirely.
        "exempt_agents": [(LOGIX, "Logix authors Server Scripts as its core function.")],
    },
    {
        "rule_name": "Deny workflow actions on payroll and financial records",
        "category": "Payroll & Financial",
        "action": "Deny",
        "enabled": 1,
        "restricted_doctypes": "\n".join([
            "Salary Slip", "Payroll Entry", "Salary Structure",
            "Salary Structure Assignment", "Employee Advance", "Employee Incentive",
            "Gratuity", "Journal Entry", "Payment Entry", "Expense Claim",
        ]),
        # Narrow on purpose: this is the only deployed tool that mutates an
        # arbitrary document. Reads stay available to HR.
        "restricted_tools": "transition_workflow",
        "violation_message": (
            "approving, rejecting or otherwise moving a payroll or financial record "
            "through its workflow has to be done by a person."
        ),
        "exempt_agents": [],
    },
    {
        "rule_name": "Deny destructive operations on submitted records",
        "category": "Destructive & Bulk",
        "action": "Deny",
        "enabled": 0,  # threshold not yet agreed - see module docstring
        "restricted_doctypes": "\n".join(["Deleted Document", "Version"]),
        "restricted_tools": "",
        "violation_message": (
            "deleting or reversing submitted records has to be done by a person."
        ),
        "exempt_agents": [],
    },
]


def execute():
    if not frappe.db.exists("DocType", "AI Tool Policy Rule"):
        print("seed_ai_tool_policy_rules: doctype missing - skipped")
        return

    created = 0
    for spec in RULES:
        if frappe.db.exists("AI Tool Policy Rule", spec["rule_name"]):
            continue
        doc = frappe.new_doc("AI Tool Policy Rule")
        doc.rule_name = spec["rule_name"]
        doc.category = spec["category"]
        doc.action = spec["action"]
        doc.enabled = spec["enabled"]
        doc.restricted_doctypes = spec["restricted_doctypes"]
        doc.restricted_tools = spec["restricted_tools"]
        doc.violation_message = spec["violation_message"]
        for agent, reason in spec["exempt_agents"]:
            # Only add the exemption when that agent exists on this site;
            # a missing link would make the whole rule unsaveable.
            if frappe.db.exists("AI Agent Configuration", agent):
                doc.append("exempt_agents", {"agent_configuration": agent, "reason": reason})
            else:
                print(f"  note: exempt agent '{agent}' not on this site - skipped")
        doc.insert(ignore_permissions=True)
        created += 1
        print(f"  created: {doc.name} (enabled={spec['enabled']})")

    if created:
        frappe.db.commit()
    print(f"seed_ai_tool_policy_rules: {created} rule(s) created")
