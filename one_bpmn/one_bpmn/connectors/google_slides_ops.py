# Copyright (c) 2026, one-fm and contributors
# Google Slides connector handlers — thin wrappers over integrations/google_slides.py.

from one_bpmn.one_bpmn.integrations import google_slides as gslides


def get_text(params, ctx):
    return {"text": gslides.get_text(params["presentation"])}
