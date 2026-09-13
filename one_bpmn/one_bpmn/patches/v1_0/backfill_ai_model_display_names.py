# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""Give every existing AI Model row a readable Display Name (WI-000360).

``display_name`` is the DocType's new ``title_field``: blank on a record made
before it existed, and blank is what a title field must never be, or every
list and link that shows the title falls back to the raw record name.

This ONLY fills a blank display_name, derived from the record's own API
identifier (``model_api_name``, falling back to the record name itself when
that field is empty). Nothing else moves:

* the record is never renamed;
* ``model_name`` and ``model_api_name`` are read, never written;
* the autoname rule (``field:model_name``) is untouched.

The derivation is a mechanical readability pass, not a lookup table, so it
keeps working on whatever a site has beyond the ids known at the time this
patch was written:

* a trailing 8-digit date (``-20250929``) is pulled out and rendered as
  ``(2025-09-29)``;
* remaining ``-``-separated numeric tokens are re-joined with ``.`` so
  ``4-6`` reads as ``4.6``, matching how ``4.1`` already looks in an id that
  carries its own dot;
* ``gpt`` is upper-cased; every other word gets an initial capital, except a
  token already mixing digits and letters (``4o``), which is a name in its
  own right and is left alone.
"""

import re

import frappe

_DATE_SUFFIX = re.compile(r"-(\d{8})$")
_DIGIT_LETTER = re.compile(r"^\d+[a-zA-Z]+$")
_DIGIT_DOTTED = re.compile(r"^\d+(\.\d+)*$")


def display_name_from_api_id(model_id: str) -> str:
	"""A readable name derived mechanically from an API id like
	``claude-sonnet-4-5-20250929`` or ``gpt-4.1-mini``."""
	s = (model_id or "").strip()
	if not s:
		return ""

	date_suffix = ""
	m = _DATE_SUFFIX.search(s)
	if m:
		d = m.group(1)
		date_suffix = f" ({d[0:4]}-{d[4:6]}-{d[6:8]})"
		s = s[: m.start()]

	tokens = s.split("-")

	# Consecutive bare-numeric tokens (4, 6) read as one version number (4.6).
	merged: list[str] = []
	for t in tokens:
		if merged and _DIGIT_DOTTED.match(merged[-1]) and t.isdigit():
			merged[-1] = f"{merged[-1]}.{t}"
		else:
			merged.append(t)

	words = []
	for t in merged:
		if not t:
			continue
		if t.lower() == "gpt":
			words.append("GPT")
		elif _DIGIT_DOTTED.match(t) or _DIGIT_LETTER.match(t):
			# Already a name in its own right (4.1, 4o) - leave as-is.
			words.append(t)
		else:
			words.append(t[:1].upper() + t[1:])

	return (" ".join(words) + date_suffix).strip()


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
		source = (row.model_api_name or row.name or "").strip()
		name = display_name_from_api_id(source)
		if not name:
			continue
		# db_set on the fetched name only - no rename, no touch to
		# model_name/model_api_name/autoname.
		frappe.db.set_value(
			"AI Model", row.name, "display_name", name, update_modified=False
		)
		filled.append(f"{row.name} -> {name}")

	frappe.db.commit()
	for line in filled:
		print(f"AI Model: display name backfilled, {line}")
