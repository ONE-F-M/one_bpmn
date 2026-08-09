# Copyright (c) 2026, one-fm and contributors
# Google Docs connector handlers — thin wrappers over integrations/google_docs.py.

import json

from one_bpmn.one_bpmn.integrations import google_docs as gdocs


def _truthy(v):
    return v is True or str(v or "").strip().lower() in ("1", "true", "yes", "on")


def append_text(params, ctx):
    return gdocs.append_text(params["document"], params.get("text") or "")


def fill_template(params, ctx):
    """Fill every placeholder in a copied template with one atomic batchUpdate.

    ``values`` is a JSON object of placeholder → replacement. It arrives as a
    string from the connector panel (and typically as rendered Jinja carrying
    the AI task's structured output), so it is parsed here.

    ``failIfUnfilled`` turns a placeholder that matched nothing into an error.
    Default on: a template that still shows ``{{owner}}`` after filling has
    almost certainly had its placeholder split across formatting runs by an
    editor, and publishing that to the domain is worse than failing.
    """
    values = params.get("values")
    if isinstance(values, str):
        values = json.loads(values or "{}")
    if not isinstance(values, dict):
        raise ValueError("fillTemplate 'values' must be a JSON object of placeholder → replacement")

    result = gdocs.fill_template(
        params["document"], values, match_case=_truthy(params.get("matchCase", True))
    )

    fail_if_unfilled = _truthy(params.get("failIfUnfilled", True))
    if fail_if_unfilled and result["unfilled"]:
        raise ValueError(
            "These placeholders were not found in the document: %s. "
            "A placeholder split across formatting runs will not match — retype it "
            "in one go with uniform formatting." % ", ".join(result["unfilled"])
        )
    return result


def get_text(params, ctx):
    return {"text": gdocs.get_text(params["document"])}


def fill_branded_template(params, ctx):
    """Fill a copy of a branded ONE-FM template that carries no placeholders.

    ``content`` is a JSON object describing the document as fields —
    ``title``/``title_ar``, optional ``intro``/``intro_ar``, a ``sections`` map
    keyed by the label printed in the template ("Purpose", "الغرض"), and
    ``items``, the numbered bilingual clauses or steps. It arrives as a string
    because it is normally the AI task's JSON output rendered through Jinja.

    ``failIfUnmatched`` is off by default here, unlike fillTemplate, and the
    difference is deliberate: the three templates do not have the same sections
    (Manual has no "Purpose:" table, SOP has no "Definitions:"), so a caller
    passing a section that a given type does not own is a normal, expected
    miss rather than a fault. Turn it on to assert an exact match. Either way
    the misses come back in ``unmatched`` so the process can be checked.
    """
    content = params.get("content")
    if isinstance(content, str):
        content = json.loads(content or "{}")
    if not isinstance(content, dict):
        raise ValueError(
            "fillBrandedTemplate 'content' must be a JSON object with "
            "title / sections / items"
        )

    result = gdocs.fill_branded_template(params["document"], content)

    if _truthy(params.get("failIfUnmatched", False)) and result["unmatched"]:
        raise ValueError(
            "These targets were not found in the document: %s. "
            "The template may have been reworded, or this document type does "
            "not have that section." % ", ".join(result["unmatched"])
        )
    return result
