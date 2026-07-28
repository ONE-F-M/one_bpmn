# Copyright (c) 2026, one-fm and contributors
# Google Sheets connector handlers — thin wrappers over integrations/google_sheets.py.

import json

from one_bpmn.one_bpmn.connectors.registry import connector
from one_bpmn.one_bpmn.integrations import google_sheets as gs


def _rows(v):
    """Coerce a values field into a 2D list (accepts a list or a JSON string)."""
    if isinstance(v, list):
        return v
    if isinstance(v, str) and v.strip():
        return json.loads(v)
    return []


@connector("google_sheets", "createSpreadsheet")
def create_spreadsheet(params, ctx):
    return gs.create_spreadsheet(params.get("title") or "Untitled Spreadsheet", params["folder"])


@connector("google_sheets", "getValues")
def get_values(params, ctx):
    return gs.get_values(params["spreadsheet"], params.get("range") or "A1:Z1000")


@connector("google_sheets", "updateValues")
def update_values(params, ctx):
    return gs.update_values(params["spreadsheet"], params["range"], _rows(params.get("values")),
                            value_input_option=params.get("valueInputOption") or "USER_ENTERED")


@connector("google_sheets", "appendValues")
def append_values(params, ctx):
    return gs.append_values(params["spreadsheet"], params.get("range") or "A1", _rows(params.get("values")),
                            value_input_option=params.get("valueInputOption") or "USER_ENTERED")


@connector("google_sheets", "clearValues")
def clear_values(params, ctx):
    return gs.clear_values(params["spreadsheet"], params["range"])


@connector("google_sheets", "addSheet")
def add_sheet(params, ctx):
    return gs.add_sheet(params["spreadsheet"], params.get("title") or "Sheet")
