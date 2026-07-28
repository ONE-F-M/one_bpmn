# Copyright (c) 2026, one-fm and contributors
# Google Sheets integration (Sheets API v4), used by the google_sheets connector.
#
# createSpreadsheet goes through the DRIVE API (files.create with the spreadsheet
# mimeType + a parent folder) rather than sheets.spreadsheets.create, so the new
# sheet lands in a Shared Drive the service account belongs to — the Sheets API's
# own create() can't target a folder and would hit the service account's (zero)
# My-Drive quota. Value operations then use the Sheets API on that id.

from one_bpmn.one_bpmn.integrations import google_common as gc

SHEET_MIME = "application/vnd.google-apps.spreadsheet"


def _svc():
    return gc.get_service("sheets", "v4", scopes=[gc.SHEETS_SCOPE, gc.DRIVE_SCOPE])


def _drive():
    return gc.get_service("drive", "v3", scopes=[gc.DRIVE_SCOPE])


def _run(request):
    return gc.call_with_retry(request.execute)


def create_spreadsheet(title: str, folder: str) -> dict:
    """Create an empty Google Sheet inside a Drive folder (Shared-Drive safe)."""
    body = {"name": title or "Untitled Spreadsheet", "mimeType": SHEET_MIME, "parents": [folder]}
    f = _run(_drive().files().create(body=body, fields="id,name,webViewLink", supportsAllDrives=True))
    return {"spreadsheetId": f.get("id"), "title": f.get("name"), "url": f.get("webViewLink")}


def get_values(spreadsheet_id: str, rng: str) -> dict:
    """spreadsheets.values.get — read a range."""
    r = _run(_svc().spreadsheets().values().get(spreadsheetId=spreadsheet_id, range=rng))
    return {"range": r.get("range"), "values": r.get("values", [])}


def update_values(spreadsheet_id: str, rng: str, values: list, value_input_option: str = "USER_ENTERED") -> dict:
    """spreadsheets.values.update — write a 2D array into a range."""
    r = _run(_svc().spreadsheets().values().update(
        spreadsheetId=spreadsheet_id, range=rng, valueInputOption=value_input_option, body={"values": values}))
    return {"updatedRange": r.get("updatedRange"), "updatedCells": r.get("updatedCells")}


def append_values(spreadsheet_id: str, rng: str, values: list, value_input_option: str = "USER_ENTERED") -> dict:
    """spreadsheets.values.append — append rows after the last row of a range."""
    r = _run(_svc().spreadsheets().values().append(
        spreadsheetId=spreadsheet_id, range=rng, valueInputOption=value_input_option,
        insertDataOption="INSERT_ROWS", body={"values": values}))
    up = r.get("updates", {}) or {}
    return {"updatedRange": up.get("updatedRange"), "updatedCells": up.get("updatedCells")}


def clear_values(spreadsheet_id: str, rng: str) -> dict:
    """spreadsheets.values.clear — clear a range."""
    r = _run(_svc().spreadsheets().values().clear(spreadsheetId=spreadsheet_id, range=rng, body={}))
    return {"clearedRange": r.get("clearedRange")}


def add_sheet(spreadsheet_id: str, title: str) -> dict:
    """spreadsheets.batchUpdate → addSheet — add a tab."""
    res = _run(_svc().spreadsheets().batchUpdate(
        spreadsheetId=spreadsheet_id, body={"requests": [{"addSheet": {"properties": {"title": title}}}]}))
    props = next(((rep.get("addSheet", {}) or {}).get("properties") for rep in res.get("replies", []) or []
                  if rep.get("addSheet")), None) or {}
    return {"spreadsheetId": spreadsheet_id, "sheetId": props.get("sheetId"), "title": props.get("title")}
