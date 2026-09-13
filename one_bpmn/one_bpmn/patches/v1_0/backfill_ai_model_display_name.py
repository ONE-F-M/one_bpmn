# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""Give every existing AI Model a readable display_name.

display_name is new, optional, and the doctype's title_field (WI-000361) so
link fields showing an AI Model show something a person can read rather than
a raw API identifier. A model created going forward may still be saved with
no display name at all \u2014 this patch only backfills rows that already exist
and are still blank.

Derivation, not invention
--------------------------
The name is derived from data already on the row: model_api_name when it is
set (that is the exact string the provider's API expects, e.g.
"claude-sonnet-4-5-20250929"), falling back to the record's own name (which is
model_name, the autoname field) when model_api_name is blank. Nothing is
guessed beyond turning that identifier into words \u2014 a trailing 8-digit date
(YYYYMMDD) becomes "(YYYY-MM-DD)", consecutive numeric segments join with a
dot ("4", "5" -> "4.5", matching how Anthropic and others already write their
own version numbers elsewhere in this catalogue), and known vendor prefixes
(gpt, o1, o3, o4) are upper-cased the way the vendor itself writes them.

Never touches model_name, model_api_name or the record's name (autoname is
untouched by this patch), and never renames a record.
"""

import re

import frappe

# Prefixes written in a fixed case by the vendor, rather than plain
# Title-casing (which would give "Gpt" instead of "GPT").
_FIXED_CASE = {"gpt": "GPT", "o1": "O1", "o3": "O3", "o4": "O4"}

_DATE_RE = re.compile(r"^\d{8}$")


def display_name_from_identifier(identifier: str) -> str:
	"""Turn an API-style model id into a readable display name.

	>>> display_name_from_identifier("claude-opus-5")
	'Claude Opus 5'
	>>> display_name_from_identifier("gpt-4.1-mini")
	'GPT 4.1 Mini'
	>>> display_name_from_identifier("claude-sonnet-4-5-20250929")
	'Claude Sonnet 4.5 (2025-09-29)'
	"""
	identifier = (identifier or "").strip()
	if not identifier:
		return ""

	tokens = identifier.split("-")

	date_suffix = ""
	if tokens and _DATE_RE.match(tokens[-1]):
		raw_date = tokens.pop()
		date_suffix = f" ({raw_date[0:4]}-{raw_date[4:6]}-{raw_date[6:8]})"

	parts = []
	i = 0
	n = len(tokens)
	while i < n:
		tok = tokens[i]
		if tok.isdigit():
			nums = [tok]
			j = i + 1
			while j < n and tokens[j].isdigit():
				nums.append(tokens[j])
				j += 1
			parts.append(".".join(nums))
			i = j
		else:
			parts.append(_FIXED_CASE.get(tok.lower(), tok.capitalize()))
			i += 1

	return " ".join(p for p in parts if p) + date_suffix


def execute():
	if not frappe.db.has_column("AI Model", "display_name"):
		return

	rows = frappe.get_all(
		"AI Model", fields=["name", "model_api_name", "display_name"]
	)
	filled = []
	for row in rows:
		if (row.display_name or "").strip():
			continue
		source = (row.model_api_name or "").strip() or row.name
		display_name = display_name_from_identifier(source)
		if not display_name:
			continue
		frappe.db.set_value(
			"AI Model", row.name, "display_name", display_name, update_modified=False
		)
		filled.append(f"{row.name} -> {display_name}")

	frappe.db.commit()
	for line in filled:
		print(f"AI Model: display_name set, {line}")
