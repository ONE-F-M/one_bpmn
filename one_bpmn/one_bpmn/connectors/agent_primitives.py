# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""
The one thing the Connector Agent cannot do from a Server Script.

Everything else the agent knows — how to read a spec, how to draft a manifest,
what makes a draft invalid, how a handler is screened, how a pull request reads —
lives in its Server Scripts, where a process owner can change it without a
developer or a deploy. This module is what is left after that move, and it is
deliberately one function.

WHY IT HAS TO BE PYTHON
-----------------------
``one_bpmn.security.script_validator.deep_inspect_script`` forbids ``requests``
in a Server Script. The obvious alternative,
``frappe.integrations.utils.make_get_request``, is not good enough here for three
reasons that all matter when the URL comes from a work order someone else wrote:

  * it offers no byte cap, and an API documentation page can be megabytes — the
    agent only wants the first slice of it for a prompt;
  * it offers no per-call timeout, so a slow host stalls the worker;
  * it raises on a non-2xx instead of reporting it, and "that URL 404s" is
    something the agent should be able to say rather than crash on.

The SSRF guard is the other reason this is one indivisible function. The URL is
attacker-influenced by construction, so the host check has to happen in the same
place as the fetch — and it reuses the connector executor's own guard rather than
a second copy that could drift into disagreeing about what is safe to call.

WHAT IT DELIBERATELY DOES NOT DO
--------------------------------
It does not decide whether the body is an OpenAPI spec, strip markup out of an
HTML page, or summarise anything. It returns the bytes it was allowed to read.
Interpreting them is the agent's job and lives in the tool script.
"""

from __future__ import annotations

import frappe

# An API reference is read into a prompt, so it is capped well below the
# connector response limit — a 2 MB HTML page is not a useful prompt and the tail
# of it is navigation furniture anyway.
MAX_REFERENCE_BYTES = 512 * 1024
FETCH_TIMEOUT = 30


def fetch_url(url: str, max_bytes: int = MAX_REFERENCE_BYTES) -> dict:
	"""Read an API reference page or machine-readable spec.

	Same outbound posture as a connector call: http(s) only, and a host that
	resolves to a private, loopback or link-local address is refused. The agent is
	handed this URL by whoever filed the work order, so without that guard it is a
	request forger.

	Returns ``{ok, url, status, content_type, body, truncated}`` on success, or
	``{ok: False, error}``. Never raises: the caller is an LLM tool loop, where an
	exception ends the turn instead of informing it.
	"""
	import requests

	from one_bpmn.one_bpmn.connectors import http_ops

	url = (url or "").strip()
	if not url:
		return {"ok": False, "error": "No URL was given to read."}
	if "://" not in url:
		url = "https://" + url

	try:
		http_ops._assert_host_allowed(url, allow_internal=False)
	except Exception as exc:  # noqa: BLE001 — a refused host is an answer, not a crash
		return {"ok": False, "error": str(exc)[:400], "url": url}

	try:
		resp = requests.get(
			url,
			timeout=FETCH_TIMEOUT,
			headers={"Accept": "application/json, application/yaml, text/html;q=0.8"},
			stream=True,
		)
		raw = resp.raw.read(max_bytes + 1, decode_content=True) or b""
	except Exception as exc:  # noqa: BLE001
		return {"ok": False, "error": f"Could not read {url}: {exc}"[:400], "url": url}

	truncated = len(raw) > max_bytes
	body = raw[:max_bytes].decode(resp.encoding or "utf-8", errors="replace")

	if resp.status_code >= 400:
		# Reported, not raised. "That URL returns 404" is a useful thing for the
		# agent to say back to whoever wrote the work order.
		return {
			"ok": False,
			"error": f"{url} returned HTTP {resp.status_code}.",
			"url": url,
			"status": resp.status_code,
			"body": body[:2000],
		}

	return {
		"ok": True,
		"url": url,
		"status": resp.status_code,
		"content_type": (resp.headers.get("Content-Type") or "").split(";")[0].strip(),
		"body": body,
		"truncated": truncated,
	}
