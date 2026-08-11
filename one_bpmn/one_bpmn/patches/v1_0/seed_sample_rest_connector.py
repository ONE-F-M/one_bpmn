# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""
Seed a worked example of a connector built entirely from configuration.

The claim the connector DocTypes make is "a REST integration needs no Python".
This is the proof, and it is deliberately something ONE-FM would actually use:
outdoor work in Kuwait is heat-limited, so a process that assigns or approves
outdoor tasks has a real reason to ask what the temperature will be.

Open-Meteo is used because it needs **no API key** — the whole connector can be
demonstrated on any site, immediately, with nothing to configure. That also
makes it the cleanest teaching example: what remains on the form is only the
parts every connector has.

Between them the two operations exercise most of what the executor can do:

    query templating          latitude/longitude/timezone from fields
    field defaults            Kuwait City, so it runs on first click
    response mapping          a deep response reduced to five useful keys
    list indexing             daily.temperature_2m_max[0] → today's peak
    no authentication         auth_type "None"

Idempotent. Re-running refreshes the configuration but never duplicates it.
"""

import json

import frappe

CONNECTOR_ID = "open_meteo"
BASE_URL = "https://api.open-meteo.com/v1"

# Kuwait City. Defaults rather than required blanks so the connector answers on
# the first click — a sample that needs three inputs before it does anything is
# a poor demonstration.
KUWAIT_CITY = {"latitude": "29.3759", "longitude": "47.9774", "timezone": "Asia/Kuwait"}

# A sun, on the 24x24 viewBox the icon renderer expects.
ICON_PATH = (
	"M12 7a5 5 0 100 10 5 5 0 000-10zM12 1v3M12 20v3M4.2 4.2l2.1 2.1"
	"M17.7 17.7l2.1 2.1M1 12h3M20 12h3M4.2 19.8l2.1-2.1M17.7 6.3l2.1-2.1"
)

LOCATION_FIELDS = [
	{
		"field_name": "latitude",
		"field_label": "Latitude",
		"field_type": "String",
		"required": 1,
		"expression": 1,
		"default_value": KUWAIT_CITY["latitude"],
		"help_text": "Decimal degrees. Defaults to Kuwait City.",
	},
	{
		"field_name": "longitude",
		"field_label": "Longitude",
		"field_type": "String",
		"required": 1,
		"expression": 1,
		"default_value": KUWAIT_CITY["longitude"],
		"help_text": "Decimal degrees. Defaults to Kuwait City.",
	},
	{
		"field_name": "timezone",
		"field_label": "Timezone",
		"field_type": "String",
		"expression": 1,
		"default_value": KUWAIT_CITY["timezone"],
		"help_text": "Times in the response are returned in this zone.",
	},
]

OPERATIONS = [
	{
		"operation_id": "currentConditions",
		"label": "Current conditions",
		"api_method": "GET /v1/forecast (current)",
		"description": (
			"Temperature, humidity and wind right now. Use it to gate outdoor work — "
			"a Script Task or gateway can compare weather.temperature against a limit."
		),
		"sort_order": 1,
		"http_method": "GET",
		"url_template": "forecast",
		"query_params_json": {
			"latitude": "{{ params.latitude }}",
			"longitude": "{{ params.longitude }}",
			"timezone": "{{ params.timezone or 'Asia/Kuwait' }}",
			"current": "temperature_2m,relative_humidity_2m,wind_speed_10m",
		},
		"response_map_json": {
			"temperature": "current.temperature_2m",
			"humidity": "current.relative_humidity_2m",
			"windSpeed": "current.wind_speed_10m",
			"observedAt": "current.time",
			"unit": "current_units.temperature_2m",
		},
		"fields": LOCATION_FIELDS,
	},
	{
		"operation_id": "dailyOutlook",
		"label": "Daily outlook",
		"api_method": "GET /v1/forecast (daily)",
		"description": (
			"Daily highs and lows for the next few days, plus today's peak on its own "
			"key so a gateway can read it without indexing a list."
		),
		"sort_order": 2,
		"http_method": "GET",
		"url_template": "forecast",
		"query_params_json": {
			"latitude": "{{ params.latitude }}",
			"longitude": "{{ params.longitude }}",
			"timezone": "{{ params.timezone or 'Asia/Kuwait' }}",
			"daily": "temperature_2m_max,temperature_2m_min",
			"forecast_days": "{{ params.days or 3 }}",
		},
		"response_map_json": {
			"dates": "daily.time",
			"maxTemps": "daily.temperature_2m_max",
			"minTemps": "daily.temperature_2m_min",
			# Bracket indexing into a list — the reason a gateway can branch on
			# "is it too hot today" without any script at all.
			"peakToday": "daily.temperature_2m_max[0]",
		},
		"fields": LOCATION_FIELDS
		+ [
			{
				"field_name": "days",
				"field_label": "Days ahead",
				"field_type": "Dropdown",
				"default_value": "3",
				"choices": "1\n3\n7\n14",
				"help_text": "How many days of forecast to return.",
			}
		],
	},
]


def execute():
	if not frappe.db.table_exists("BPMN Connector"):
		return

	doc = (
		frappe.get_doc("BPMN Connector", CONNECTOR_ID)
		if frappe.db.exists("BPMN Connector", CONNECTOR_ID)
		else frappe.new_doc("BPMN Connector")
	)
	doc.connector_id = CONNECTOR_ID
	doc.label = "Weather (Open-Meteo)"
	doc.description = (
		"Worked example of a connector that is pure configuration — no Python anywhere. "
		"Open-Meteo is a free public API and needs no key, so this works on any site as "
		"soon as it is installed. Practical use: gate outdoor work on temperature."
	)
	doc.enabled = 1
	doc.execution_type = "HTTP Request"
	doc.base_url = BASE_URL
	doc.auth_type = "None"
	doc.request_timeout = 20
	doc.icon_svg_path = ICON_PATH
	doc.icon_color = "#f59e0b"
	doc.icon_label = "Weather"
	doc.save(ignore_permissions=True)

	for spec in OPERATIONS:
		_upsert_operation(spec)

	from one_bpmn.one_bpmn.connectors.manifest import clear_manifest_cache

	clear_manifest_cache()
	frappe.db.commit()
	print(f"Sample connector {CONNECTOR_ID!r} seeded with {len(OPERATIONS)} operations")


def _upsert_operation(spec):
	name = frappe.db.get_value(
		"BPMN Connector Operation",
		{"connector": CONNECTOR_ID, "operation_id": spec["operation_id"]},
		"name",
	)
	op = (
		frappe.get_doc("BPMN Connector Operation", name)
		if name
		else frappe.new_doc("BPMN Connector Operation")
	)
	op.connector = CONNECTOR_ID
	op.enabled = 1
	for key in ("operation_id", "label", "api_method", "description", "sort_order",
	            "http_method", "url_template"):
		op.set(key, spec[key])
	op.execution_type = "HTTP Request"
	op.query_params_json = json.dumps(spec["query_params_json"], indent=2)
	op.response_map_json = json.dumps(spec["response_map_json"], indent=2)

	# Rebuilt rather than merged, so re-running converges on exactly this spec.
	op.fields = []
	for field in spec["fields"]:
		op.append("fields", field)
	op.save(ignore_permissions=True)
