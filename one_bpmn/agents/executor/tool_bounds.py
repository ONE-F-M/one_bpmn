# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""
Bounds on what passes between the model and its tools (WI-002195).

Two controls, both applied in the step loop so every tool of every agent gets
them — shape tools, skills, delegation, sandbox tools and the answer a person
gives on a resumed turn alike.

**Results are size-bounded.** A tool's answer is pasted into the conversation
the model reads on every later call of the turn, and nothing capped it:
LuCrusher's codebase scan once put 76,893 characters (about 19k tokens) into
context in a single call. Over the cap, the model-facing copy is cut and told
so, with the instruction to ask again more narrowly. The audit copy on the AI
Agent Tool Call row is never cut — the cap is about what the model pays to
re-read, not about what was recorded.

**Arguments are validated before the script runs.** A shape declares what its
tool needs (``aiToolParams``), but the platform handed the model's arguments
straight to the script. A missing argument surfaced as a Python error message,
or as nothing at all when the script tolerated the gap and produced a wrong
answer. The declared schema is now checked first, and a violation goes back to
the model as a tool error naming the field, without the script having run.
"""

from __future__ import annotations

from frappe import _

# The default cap when an agent's configuration leaves the field blank. Large
# enough that an ordinary tool answer is never touched — a Work Item, a search
# page, a schema — and small enough that a single dump cannot dominate a turn.
DEFAULT_TOOL_RESULT_MAX_CHARS = 20000

# Never cut below this whatever the configuration says: a cap of 50 characters
# would leave the model nothing but the trailer.
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
	"""The model-facing copy of a tool result, cut at the cap with a trailer.

	Returns a string either way. Under the cap the text comes back unchanged, so
	an agent whose tools already behave pays nothing for the check.
	"""
	text = result if isinstance(result, str) else str(result)
	cap = effective_max_chars(max_chars)
	if len(text) <= cap:
		return text
	omitted = len(text) - cap
	return text[:cap] + "\n" + truncation_trailer(omitted)


def validate_tool_arguments(tool_name: str, parameters: dict | None, required: list | None, arguments) -> str | None:
	"""Check the model's arguments against the tool's declared schema.

	Returns None when the call may proceed, or the tool error the model should
	see instead of a result. A tool that declares nothing is not checked — there
	is no schema to check against, and a zero-argument tool must keep working.
	"""
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

	# Missing required arguments first, in the words the acceptance criterion
	# uses, because that is the failure the model can most easily repair.
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
