# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""
Seed the "url_liveness_check" Connector: a plain HTTP GET request against a
caller-supplied URL, with no fixed base_url (the operation's own url_template
is the whole, absolute URL) and no auth.

This exists so "Threat Source Discovery" can check whether its already-approved
Threat Source URLs are still reachable — the one thing its own process
documentation named as deliberately dropped rather than ported from onefm_mcp's
retired source_validator.py, because a plain Script Task can never do this
itself: one_bpmn's security gate (one_bpmn.security.script_validator) forbids
`requests`/`urllib` outright, so any outbound call has to go through a
Connector, dispatched from a Service Task, not from inside a script's Python.

Idempotent via the same import_manifest path every other connector uses — a
connector that already exists on a site (hand-edited or otherwise) is left
alone unless overwrite=True.
"""

import frappe

URL_LIVENESS_CONNECTOR = {
	"connectorId": "url_liveness_check",
	"label": "URL Liveness Check",
	"description": (
		"Checks whether a URL is still reachable with a plain HTTP GET request. "
		"No auth, no fixed base URL — the operation's URL Template is the whole "
		"caller-supplied URL."
	),
	"execution": {
		"type": "HTTP Request",
		"baseUrl": "",
		"timeout": 20,
	},
	"operations": [
		{
			"value": "check",
			"label": "Check URL is reachable (GET)",
			"description": (
				"GET request against the given URL — BPMN Connector Operation's "
				"http_method Select does not offer HEAD, only GET/POST/PUT/PATCH/"
				"DELETE. Raises on a non-2xx/3xx response or a network failure, "
				"same as the connector's usual error contract — the caller reads "
				"that as reachable vs not by whether the Service Task's result "
				"variable is None."
			),
			"executionType": "HTTP Request",
			"http": {
				"method": "GET",
				"url": "{{ params.url }}",
				# Liveness only needs a status, not the page — an unmapped
				# response would carry the full response body (up to
				# _MAX_RESPONSE_BYTES, 2MB) into every Multi-Instance
				# iteration's output, and 20+ of those in one process
				# instance's persisted workflow_state can exceed MySQL's
				# max_allowed_packet on save ("MySQL server has gone away").
				"responseMap": {"statusCode": "statusCode"},
			},
			"fields": [
				{"name": "url", "label": "URL", "type": "String", "required": True},
			],
		}
	],
}


def execute():
	from one_bpmn.one_bpmn.connectors.seed import import_manifest

	import_manifest(URL_LIVENESS_CONNECTOR, overwrite=False)
	frappe.db.commit()
