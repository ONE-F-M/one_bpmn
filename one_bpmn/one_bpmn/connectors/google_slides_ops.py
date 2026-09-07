# Copyright (c) 2026, one-fm and contributors
# Google Slides connector handlers — thin wrappers over integrations/google_slides.py.

import json

from one_bpmn.one_bpmn.integrations import google_slides as gslides


def _truthy(v):
    return v is True or str(v or "").strip().lower() in ("1", "true", "yes", "on")


def get_text(params, ctx):
    return {"text": gslides.get_text(params["presentation"])}


def fill_branded_deck(params, ctx):
    """Fill a copy of the branded ONE-FM Guideline deck.

    ``content`` is a JSON object describing the guideline as fields -
    ``guideline_name``, ``pages`` (a title/body pair per slide), and the
    ``dos``/``donts`` lists. It arrives as a string because it is normally the
    AI task's JSON output rendered through Jinja.

    ``failIfUnmatched`` is off by default, matching fillBrandedTemplate: a
    guideline with no do's and don'ts is ordinary, not a fault. The misses come
    back in ``unmatched`` either way so the process can be checked.
    """
    content = params.get("content")
    if isinstance(content, str):
        content = json.loads(content or "{}")
    if not isinstance(content, dict):
        raise ValueError(
            "fillBrandedDeck 'content' must be a JSON object with "
            "guideline_name / pages / dos / donts"
        )

    result = gslides.fill_branded_deck(params["presentation"], content)

    if _truthy(params.get("failIfUnmatched", False)) and result["unmatched"]:
        raise ValueError(
            "These targets were not found in the deck: %s. "
            "The template may have been restructured - the fill locates its "
            "targets by position on the slide."
            % ", ".join(result["unmatched"])
        )
    return result
