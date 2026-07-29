# Copyright (c) 2026, one-fm and contributors
# Google Docs connector handlers — thin wrappers over integrations/google_docs.py.

from one_bpmn.one_bpmn.connectors.registry import connector
from one_bpmn.one_bpmn.integrations import google_docs as gdocs


def _truthy(v):
    return v is True or str(v or "").strip().lower() in ("1", "true", "yes", "on")


@connector("google_docs", "createDocument")
def create_document(params, ctx):
    return gdocs.create_document(params.get("title") or "Untitled Document", params.get("folder"))


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


@connector("google_docs", "getText")
def get_text(params, ctx):
    return {"text": gdocs.get_text(params["document"])}
