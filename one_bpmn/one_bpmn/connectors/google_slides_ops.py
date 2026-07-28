# Copyright (c) 2026, one-fm and contributors
# Google Slides connector handlers — thin wrappers over integrations/google_slides.py.

from one_bpmn.one_bpmn.connectors.registry import connector
from one_bpmn.one_bpmn.integrations import google_slides as gslides


@connector("google_slides", "createPresentation")
def create_presentation(params, ctx):
    return gslides.create_presentation(params.get("title") or "Untitled Presentation")


@connector("google_slides", "replaceAllText")
def replace_all_text(params, ctx):
    match_case = str(params.get("matchCase") or "").strip().lower() in ("1", "true", "yes", "on")
    return gslides.replace_all_text(params["presentation"], params.get("find") or "",
                                    params.get("replace") or "", match_case=match_case)


@connector("google_slides", "createSlide")
def create_slide(params, ctx):
    return gslides.create_slide(params["presentation"], layout=params.get("layout") or None)


@connector("google_slides", "duplicateSlide")
def duplicate_slide(params, ctx):
    return gslides.duplicate_slide(params["presentation"], params["slideObjectId"])


@connector("google_slides", "getText")
def get_text(params, ctx):
    return {"text": gslides.get_text(params["presentation"])}
