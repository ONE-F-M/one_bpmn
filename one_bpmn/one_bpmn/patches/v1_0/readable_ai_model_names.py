# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""Put a readable name in AI Model's Model Name, so pickers stop showing API ids.

Model Name held the same string as the record's own name and as Model API Name —
"claude-sonnet-4-5-20250929" three times over — so every model dropdown in
Processa listed identifiers. Model Name is now the label (it is the doctype's
title field) and Model API Name stays the exact string the provider expects.

Nothing is renamed. Model Name is the autoname source, but Frappe reads it only
when a record is inserted, so rewriting it later leaves record names alone —
which matters, because a rename would not reach the model ids written as plain
text into process maps, compiled specs and Server Scripts. Written with
db.set_value for the same reason a rename is avoided: saving the document would
run the credential probe against the provider for all eighteen rows.

Only rows whose Model Name still looks like an identifier are touched, so a name
somebody has already written by hand survives the patch.
"""

import re

import frappe

# Prefixes a vendor writes in a fixed case, rather than plain title-casing
# (which would give "Gpt" instead of "GPT").
_FIXED_CASE = {"gpt": "GPT", "o1": "O1", "o3": "O3", "o4": "O4"}

_DATE_RE = re.compile(r"^\d{8}$")


def readable_name(identifier: str) -> str:
	"""Turn an API-style model id into a readable name.

	>>> readable_name("claude-opus-5")
	'Claude Opus 5'
	>>> readable_name("gpt-4.1-mini")
	'GPT 4.1 Mini'
	>>> readable_name("claude-sonnet-4-5-20250929")
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
	index = 0
	while index < len(tokens):
		token = tokens[index]
		if token.isdigit():
			# "4", "5" -> "4.5", the way the vendors write their own versions.
			numbers = [token]
			ahead = index + 1
			while ahead < len(tokens) and tokens[ahead].isdigit():
				numbers.append(tokens[ahead])
				ahead += 1
			parts.append(".".join(numbers))
			index = ahead
		else:
			parts.append(_FIXED_CASE.get(token.lower(), token.capitalize()))
			index += 1

	return " ".join(part for part in parts if part) + date_suffix


def _still_an_identifier(name: str) -> bool:
	"""A name nobody has written yet: no spaces, and lower case throughout."""
	name = (name or "").strip()
	return bool(name) and " " not in name and name == name.lower()


def execute():
	for row in frappe.get_all("AI Model", fields=["name", "model_name", "model_api_name"]):
		if not _still_an_identifier(row.model_name):
			continue
		readable = readable_name((row.model_api_name or "").strip() or row.name)
		if not readable or readable == row.model_name:
			continue
		frappe.db.set_value(
			"AI Model", row.name, "model_name", readable, update_modified=False
		)
		print(f"AI Model {row.name}: model_name -> {readable}")
