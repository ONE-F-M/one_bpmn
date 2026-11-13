# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""Small helpers shared by the whitelisted API modules."""

from __future__ import annotations

import json

import frappe


def distinct(doctype: str, fieldname: str, limit: int = 200) -> list:
	"""The non-empty values a field actually holds, sorted ascending."""
	rows = frappe.get_all(
		doctype,
		filters={fieldname: ["is", "set"]},
		fields=[fieldname],
		group_by=fieldname,
		order_by=f"{fieldname} asc",
		limit=limit,
	)
	return [r[fieldname] for r in rows if r.get(fieldname)]


def parse_json_or_passthrough(value, fallback=None):
	"""Dicts and lists pass through, JSON text is parsed, anything else gives the fallback."""
	if value in (None, ""):
		return fallback
	if isinstance(value, (dict, list)):
		return value
	try:
		return json.loads(value)
	except (json.JSONDecodeError, TypeError, ValueError):
		return fallback


def shape_reply(result: dict, trigger_keys: tuple, copy_keys: tuple) -> dict:
	"""Lift a JSON contract out of a text reply; a no-op when a trigger key is already set."""
	if any(result.get(key) for key in trigger_keys):
		return result
	from processa.ai_agent_registry.definitions.shared.helpers import extract_json

	raw = result.get("response") or ""
	parsed = extract_json(raw if isinstance(raw, str) else "")
	if not isinstance(parsed, dict) or not any(parsed.get(key) for key in trigger_keys):
		return result
	shaped = dict(result)
	shaped["response"] = str(parsed.get("response") or "").strip() or raw
	for key in copy_keys:
		if parsed.get(key):
			shaped[key] = parsed[key]
	return shaped
