# Copyright (c) 2026, one-fm and contributors
"""Google Docs connector handlers over google/docs.py."""

import json

from processa.processa_connectors.google import docs as gdocs


def _truthy(v):
	return v is True or str(v or "").strip().lower() in ("1", "true", "yes", "on")


def append_text(params, ctx):
	return gdocs.append_text(params["document"], params.get("text") or "")


def fill_template(params, ctx):
	"""Fill every placeholder in a copied template from values, a JSON object of placeholder to replacement.

	failIfUnfilled, on by default, turns a placeholder that matched nothing into an error.
	"""
	values = params.get("values")
	if isinstance(values, str):
		values = json.loads(values or "{}")
	if not isinstance(values, dict):
		raise ValueError("fillTemplate 'values' must be a JSON object of placeholder to replacement")

	result = gdocs.fill_template(
		params["document"], values, match_case=_truthy(params.get("matchCase", True))
	)

	fail_if_unfilled = _truthy(params.get("failIfUnfilled", True))
	if fail_if_unfilled and result["unfilled"]:
		raise ValueError(
			"These placeholders were not found in the document: %s. "
			"A placeholder split across formatting runs will not match - retype it "
			"in one go with uniform formatting." % ", ".join(result["unfilled"])
		)
	return result


def get_text(params, ctx):
	return {"text": gdocs.get_text(params["document"])}


def fill_branded_template(params, ctx):
	"""Fill a copy of a branded ONE-FM template from content: title, title_ar, intro, intro_ar, sections and items.

	failIfUnmatched is off by default because the three templates do not share every section; misses come back in unmatched.
	"""
	content = params.get("content")
	if isinstance(content, str):
		content = json.loads(content or "{}")
	if not isinstance(content, dict):
		raise ValueError("fillBrandedTemplate 'content' must be a JSON object with title / sections / items")

	result = gdocs.fill_branded_template(params["document"], content)

	if _truthy(params.get("failIfUnmatched", False)) and result["unmatched"]:
		raise ValueError(
			"These targets were not found in the document: %s. "
			"The template may have been reworded, or this document type does "
			"not have that section." % ", ".join(result["unmatched"])
		)
	return result
