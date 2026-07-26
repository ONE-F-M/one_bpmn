# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""
Seed patch: create sample AI Provider Credentials records for developer mode.
Guarded by frappe.conf.developer_mode — never runs in production.
"""
import frappe


def execute():
    if not frappe.conf.get("developer_mode"):
        return

    providers = [
        {
            "provider_name": "openai-dev",
            "provider_type": "OpenAI",
            "api_endpoint": "https://api.openai.com/v1",
            "api_key": "dev-placeholder-openai-key",
            "default_model": "gpt-4o",
            "enabled": 1,
        },
        {
            "provider_name": "anthropic-dev",
            "provider_type": "Anthropic",
            "api_endpoint": "https://api.anthropic.com/v1",
            "api_key": "dev-placeholder-anthropic-key",
            "default_model": "claude-sonnet-4-20250514",
            "enabled": 1,
        },
    ]

    inserted = False
    for p in providers:
        if frappe.db.exists("AI Provider Credentials", p["provider_name"]):
            continue
        doc = frappe.get_doc({"doctype": "AI Provider Credentials", **p})
        doc.insert(ignore_permissions=True)
        inserted = True

    if inserted:
        frappe.db.commit()
