# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""Bounds on what passes between the model and its tools."""

from __future__ import annotations

import re

import frappe
from frappe import _

DEFAULT_TOOL_RESULT_MAX_CHARS = 20000

# Floor for any configured cap, so the model always gets more than the trailer.
MIN_TOOL_RESULT_MAX_CHARS = 500


def effective_max_chars(configured: int | None) -> int:
	"""The cap in force: the configured value, floored, or the default."""
	try:
		value = int(configured or 0)
	except (TypeError, ValueError):
		value = 0
	if value <= 0:
		return DEFAULT_TOOL_RESULT_MAX_CHARS
	return max(value, MIN_TOOL_RESULT_MAX_CHARS)


def truncation_trailer(omitted: int) -> str:
	return f"[truncated, {omitted} more characters; call again with a narrower request]"


def bound_tool_result(result, max_chars: int | None) -> str:
	"""The model-facing copy of a tool result, cut at the cap with a trailer."""
	text = result if isinstance(result, str) else str(result)
	cap = effective_max_chars(max_chars)
	if len(text) <= cap:
		return text
	omitted = len(text) - cap
	return text[:cap] + "\n" + truncation_trailer(omitted)


def validate_tool_arguments(
	tool_name: str, parameters: dict | None, required: list | None, arguments
) -> str | None:
	"""Check the model's arguments against the tool's declared schema."""
	parameters = parameters or {}
	required = list(required or [])
	if not parameters and not required:
		return None

	if arguments is None:
		arguments = {}
	if not isinstance(arguments, dict):
		return _("Arguments for tool {0} must be a JSON object, got {1}").format(
			tool_name, type(arguments).__name__
		)

	for field in required:
		if field not in arguments or arguments[field] is None:
			return _("Missing required argument '{0}' for tool {1}").format(field, tool_name)

	try:
		import jsonschema
	except ImportError:  # pragma: no cover - jsonschema ships with Frappe
		return None

	schema = {"type": "object", "properties": parameters, "required": required}
	validator_cls = jsonschema.validators.validator_for(schema)
	errors = sorted(validator_cls(schema).iter_errors(arguments), key=lambda e: list(e.path))
	if not errors:
		return None
	return _describe(tool_name, errors[0])


def _describe(tool_name: str, error) -> str:
	"""One sentence the model can act on, naming the argument."""
	path = [str(p) for p in error.absolute_path]
	field = path[0] if path else ""
	if error.validator == "type" and field:
		expected = error.validator_value
		if isinstance(expected, list):
			expected = " or ".join(str(e) for e in expected)
		return _("Argument '{0}' for tool {1} must be {2}, got {3}").format(
			field, tool_name, expected, _json_type(error.instance)
		)
	if error.validator == "enum" and field:
		return _("Argument '{0}' for tool {1} must be one of: {2}").format(
			field, tool_name, ", ".join(str(v) for v in error.validator_value)
		)
	where = ".".join(path) if path else _("the arguments")
	return _("Invalid argument for tool {0} at {1}: {2}").format(tool_name, where, error.message)


def _json_type(value) -> str:
	if value is None:
		return "null"
	if isinstance(value, bool):
		return "boolean"
	if isinstance(value, int):
		return "integer"
	if isinstance(value, float):
		return "number"
	if isinstance(value, str):
		return "string"
	if isinstance(value, list):
		return "array"
	if isinstance(value, dict):
		return "object"
	return type(value).__name__


_LEAKED_PARAMETER = re.compile(r"<parameter\s+name=\"([^\"]+)\"\s*>(.*?)(?=<parameter\s+name=|\Z)", re.S)
_LEAKED_DELIMITER = re.compile(r"</?parameter[^>]*>|</?invoke[^>]*>")


def salvage_leaked_delimiters(tool_name: str, parameters: dict | None, arguments):
	"""Strip tool-call delimiters the model wrote into a string argument, recovering any argument they opened."""
	if not isinstance(arguments, dict):
		return arguments
	declared = parameters or {}
	repaired = dict(arguments)
	for key, value in arguments.items():
		if not isinstance(value, str):
			continue
		cuts = [i for i in (value.find(f"</{key}>"), _first_start(_LEAKED_PARAMETER, value)) if i >= 0]
		if not cuts and not _LEAKED_DELIMITER.search(value):
			continue
		cut = min(cuts, default=len(value))
		for match in _LEAKED_PARAMETER.finditer(value, cut):
			name, recovered = match.group(1), _LEAKED_DELIMITER.sub("", match.group(2)).strip()
			if not recovered or name == key or name not in declared:
				continue
			if declared[name].get("type") == "array":
				existing = repaired.get(name) or []
				repaired[name] = [*(existing if isinstance(existing, list) else [existing]), recovered]
			elif not repaired.get(name):
				repaired[name] = recovered
		repaired[key] = _LEAKED_DELIMITER.sub("", value[:cut]).strip()
		frappe.logger("tool_arguments").info(f"stripped leaked tool-call delimiters from {tool_name}.{key}")
	return repaired


def _first_start(pattern, text: str) -> int:
	match = pattern.search(text)
	return match.start() if match else -1
