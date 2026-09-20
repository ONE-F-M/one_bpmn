# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""
Seed the "nager_date_holidays" Connector \u2014 a plain HTTP GET request against the
Nager.Date public holidays API (https://date.nager.at), no auth, no fixed
per-country baseUrl beyond the shared API root.

WI-000417: a BPMN process needs Kuwait's public holidays for a given year to
schedule around them. Nager.Date documents one endpoint that answers this:

    GET https://date.nager.at/api/v3/PublicHolidays/{year}/{countryCode}

which for Kuwait (country code "KW") returns a JSON array such as:

    [
      {"date": "2026-01-01", "localName": "New Year's Day", "name": "New Year's Day",
       "countryCode": "KW", "fixed": true, "global": true, "counties": null,
       "launchYear": null, "types": ["Public"]},
      ...
    ]

There is no per-operation Python handler here on purpose \u2014 the call is a bare
GET with no body, no query params and no auth, which the declarative HTTP
executor (connectors/http_ops.py) already does in full. Leaving the operation's
Response Map empty means the whole JSON array reaches task data (http_ops wraps
a non-dict response as {"response": [...]}), which is what a modeler wants here:
every holiday's date and name, not a cherry-picked subset.

No-data handling: Nager.Date answers a year/country with no holiday data (e.g.
a year far outside its coverage) with HTTP 200 and an empty JSON array, not an
error status. That passes straight through the executor's normal 2xx path, so
the Service Task's result variable naturally becomes {"response": []} \u2014 an
empty list with no exception raised, exactly what "handle gracefully" asks for.
A genuine failure (network error, non-2xx) still raises ConnectorHTTPError as
usual, which is the connector framework's standard error contract.

Idempotent via the same import_manifest path every other connector uses \u2014 a
connector that already exists on a site (hand-edited or otherwise) is left
alone unless overwrite=True.
"""

import frappe

NAGER_DATE_HOLIDAYS_CONNECTOR = {
	"connectorId": "nager_date_holidays",
	"label": "Nager.Date Public Holidays",
	"description": (
		"Looks up public holidays for a given year from the free Nager.Date "
		"API (https://date.nager.at). No authentication required."
	),
	"api": {
		"name": "Nager.Date",
		"version": "v3",
		"discovery": "https://date.nager.at/swagger/index.html",
	},
	"execution": {
		"type": "HTTP Request",
		"baseUrl": "https://date.nager.at/api/v3",
		"timeout": 20,
	},
	"operations": [
		{
			"value": "getKuwaitPublicHolidays",
			"label": "Get Kuwait Public Holidays",
			"method": "GET /PublicHolidays/{year}/KW",
			"description": (
				"Fetches Kuwait's public holidays for the given year from Nager.Date. "
				"Returns an empty list, not an error, when the API has no data for "
				"that year."
			),
			"executionType": "HTTP Request",
			"http": {
				"method": "GET",
				"url": "/PublicHolidays/{{ params.year }}/KW",
			},
			"fields": [
				{
					"name": "year",
					"label": "Year",
					"type": "String",
					"required": True,
					"help": (
						"Four-digit year to look up, e.g. 2026. Kuwait's country code "
						"(KW) is fixed by this operation."
					),
				},
			],
			"output": {
				"response": (
					"Array of Kuwait public holidays for the year, each with date, "
					"localName, name and other Nager.Date fields. Empty array (not "
					"an error) when the API holds no data for that year."
				)
			},
		}
	],
}


def execute():
	from one_bpmn.one_bpmn.connectors.seed import import_manifest

	import_manifest(NAGER_DATE_HOLIDAYS_CONNECTOR, overwrite=False)
	frappe.db.commit()
