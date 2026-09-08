"""LuCrusher fetches a Lucidchart document once per conversation.

Every chat turn is a fresh run, so the parse never outlived the turn that paid
for it: the same Subcontractor document (~30 kB) was fetched ten times in twelve
sampled runs, each one a Lucid API round-trip and ~7.4k prompt tokens the model
had already read. The full parse now lives in the conversation's session state,
keyed by document id. A repeat request gets a short marker that lists the pages;
"<id>#page=3" returns one page in detail and "<id>#refresh" fetches again for a
document edited since. finalize still receives the full parse either way, so the
frontend is unchanged.

The tail of the tool script is replaced; the parser above it is not touched.
Idempotent: a script already reading the new way is left alone.
"""

import frappe

SCRIPT = "LuCrusher – Tool Fetch Lucidchart Document"

# The first line of the tail this patch replaces; everything after it is the old
# fetch-then-trim ending.
ANCHOR = '_lcr_full = _lucrusher_fetch_lucidchart(frappe, task_data.get("document_id_or_url") or "")'
MARK = "lucid_doc:"

NEW_TAIL = '''def _lucrusher_seen_marker(doc):
    # What a repeat request gets instead of the body: enough to recognise the
    # document and to ask for one page of it. finalize has the full parse.
    pages = []
    idx = 0
    for p in (doc.get("pages") or []):
        idx += 1
        pages.append({
            "page": idx,
            "title": p.get("page_title") or ("Page " + str(idx)),
            "shape_count": p.get("shape_count", 0),
        })
    return {
        "document_id": doc.get("document_id"),
        "title": doc.get("title"),
        "page_count": doc.get("page_count") or len(pages),
        "total_shapes": doc.get("total_shapes"),
        "total_lines": doc.get("total_lines"),
        "already_fetched": True,
        "pages": pages,
        "note": (
            "This document was already fetched earlier in this conversation; its full "
            "parse is kept server-side and finalize delivers it, so do not fetch it again "
            "to answer. To read one page in detail call this tool with "
            "'<document_id>#page=<n>'. Append '#refresh' only if the document has changed "
            "in Lucidchart since."
        ),
    }


def _lucrusher_page_detail(doc, page_no):
    # One page, untrimmed apart from the raw shape dump the model never needs.
    pages = doc.get("pages") or []
    if page_no < 1 or page_no > len(pages):
        return {
            "document_id": doc.get("document_id"),
            "title": doc.get("title"),
            "error": "Page " + str(page_no) + " does not exist; the document has " + str(len(pages)) + " page(s).",
        }
    page = dict(pages[page_no - 1])
    page.pop("raw_shapes", None)
    return {
        "document_id": doc.get("document_id"),
        "title": doc.get("title"),
        "page": page_no,
        "page_count": len(pages),
        "detail": page,
    }


# ── Fetched once per conversation ─────────────────────────────────────────
# Every turn is a fresh run, so the parse never outlived the turn that paid for
# it. It is kept in the conversation's session state under the document id; a
# repeat request gets the marker above, "#page=<n>" one page in detail, and
# "#refresh" a new fetch. The turn store still gets the full parse on every
# path, so finalize and the frontend see exactly what they saw before.
from one_bpmn.agents.memory import session_state as _lcr_state
import re as _lcr_re

_lcr_input = (task_data.get("document_id_or_url") or "").strip()
_lcr_page = None
_lcr_refresh = False
_lcr_suffix = _lcr_re.search(r"#(?:page=(\\d+)|(refresh))\\s*$", _lcr_input, _lcr_re.IGNORECASE)
if _lcr_suffix:
    _lcr_input = _lcr_input[:_lcr_suffix.start()].rstrip()
    if _lcr_suffix.group(1):
        _lcr_page = int(_lcr_suffix.group(1))
    else:
        _lcr_refresh = True

_lcr_id = _lcr_re.search(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", _lcr_input, _lcr_re.IGNORECASE
)
_lcr_key = ("lucid_doc:" + _lcr_id.group(0).lower()) if _lcr_id else None

_lcr_full = None
if _lcr_key and not _lcr_refresh:
    _lcr_full = _lcr_state.get_value(context_docname, _lcr_key)
_lcr_hit = isinstance(_lcr_full, dict) and not _lcr_full.get("error")

if not _lcr_hit:
    _lcr_full = _lucrusher_fetch_lucidchart(frappe, _lcr_input)
    if _lcr_key and not _lcr_full.get("error"):
        _lcr_state.record(context_docname, {_lcr_key: _lcr_full})

update_turn(context_docname, full_document=_lcr_full)
if _lcr_page and not _lcr_full.get("error"):
    result["document"] = _lucrusher_page_detail(_lcr_full, _lcr_page)
elif _lcr_hit:
    result["document"] = _lucrusher_seen_marker(_lcr_full)
else:
    result["document"] = _lucrusher_trim_document(_lcr_full)
'''


def execute():
	if not frappe.db.exists("Server Script", SCRIPT):
		return
	code = frappe.db.get_value("Server Script", SCRIPT, "script") or ""
	if MARK in code:
		return
	if ANCHOR not in code:
		frappe.log_error(
			title="LuCrusher fetch cache: tail not found",
			message=f"{SCRIPT} no longer ends on the expected fetch-then-trim tail; add the cache by hand.",
		)
		return
	head, _, _ = code.partition(ANCHOR)
	frappe.db.set_value("Server Script", SCRIPT, "script", head + NEW_TAIL, update_modified=False)
	frappe.db.commit()
