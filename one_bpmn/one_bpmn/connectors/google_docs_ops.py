# Copyright (c) 2026, one-fm and contributors
# Google Docs connector handlers — thin wrappers over integrations/google_docs.py.

import json

from one_bpmn.one_bpmn.connectors.registry import connector
from one_bpmn.one_bpmn.integrations import google_docs as gdocs


def _truthy(v):
    return v is True or str(v or "").strip().lower() in ("1", "true", "yes", "on")


@connector("google_docs", "createDocument")
def create_document(params, ctx):
    return gdocs.create_document(params.get("title") or "Untitled Document")


@connector("google_docs", "insertText")
def insert_text(params, ctx):
    return gdocs.insert_text(params["document"], params.get("text") or "", index=int(params.get("index") or 1))


@connector("google_docs", "appendText")
def append_text(params, ctx):
    return gdocs.append_text(params["document"], params.get("text") or "")


@connector("google_docs", "replaceAllText")
def replace_all_text(params, ctx):
    return gdocs.replace_all_text(params["document"], params.get("find") or "",
                                  params.get("replace") or "", match_case=_truthy(params.get("matchCase")))


@connector("google_docs", "fillTemplate")
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


@connector("google_docs", "getText")
def get_text(params, ctx):
    return {"text": gdocs.get_text(params["document"])}
