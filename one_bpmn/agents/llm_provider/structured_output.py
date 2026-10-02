# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""Response Format JSON: the schema an agent declares, and reading the reply against it.

One place for every executor and adapter, so a JSON agent behaves the same on
Anthropic, OpenAI and Gemini.
"""

from __future__ import annotations

import json
from typing import Any

# Rules at least one provider's native JSON mode rejects.
_UNSUPPORTED_RULES = ("minimum", "maximum", "minLength", "maxLength")

_SCHEMA_KEYWORDS = frozenset(
	{
		"type",
		"properties",
		"required",
		"additionalProperties",
		"items",
		"enum",
		"anyOf",
		"oneOf",
		"allOf",
		"$ref",
		"$defs",
		"definitions",
	}
)

_LENGTH_STOPS = frozenset({"max_tokens", "length", "MAX_TOKENS"})
_SAFETY_STOPS = frozenset(
	{"refusal", "content_filter", "SAFETY", "RECITATION", "BLOCKLIST", "PROHIBITED_CONTENT"}
)


class ReplyRejected(ValueError):
	"""The reply is not the declared JSON. ``retry`` is False when asking again cannot help."""

	def __init__(self, message: str, retry: bool):
		super().__init__(message)
		self.retry = retry


class UnsupportedSchemaRule(ValueError):
	def __init__(self, rule: str, field: str):
		self.rule = rule
		self.field = field
		super().__init__(
			f"the response schema uses '{rule}' on field '{field}', which not every AI provider accepts"
		)


def normalize_response_schema(raw: Any) -> dict:
	"""A JSON Schema from what the author saved: a full schema as written, or an example object converted."""
	parsed = json.loads(raw) if isinstance(raw, str) else raw
	if not isinstance(parsed, dict):
		raise ValueError("the response schema must be a JSON object")
	if _SCHEMA_KEYWORDS & set(parsed):
		return parsed
	return schema_from_example(parsed)


def schema_from_example(example: dict) -> dict:
	"""Each value's type sets the field type; every key is required and nothing else is allowed."""
	return {
		"type": "object",
		"properties": {key: _field_from_example(value) for key, value in example.items()},
		"required": list(example),
		"additionalProperties": False,
	}


def _field_from_example(value: Any) -> dict:
	if value is None:
		return {"type": ["string", "null"]}
	if isinstance(value, bool):
		return {"type": "boolean"}
	if isinstance(value, (int, float)):
		return {"type": "number"}
	if isinstance(value, list):
		return {"type": "array", "items": _field_from_example(value[0]) if value else {}}
	if isinstance(value, dict):
		return schema_from_example(value)
	return {"type": "string"}


def validate_schema_rules(schema: dict) -> None:
	"""Raise UnsupportedSchemaRule for recursion, length or range rules, or additionalProperties other than false."""
	_check_rules(schema, "", frozenset())


def _check_rules(schema: Any, path: str, refs: frozenset) -> None:
	if not isinstance(schema, dict):
		return
	field = path or "(root)"
	for rule in _UNSUPPORTED_RULES:
		if rule in schema:
			raise UnsupportedSchemaRule(rule, field)
	if schema.get("additionalProperties", False) is not False:
		raise UnsupportedSchemaRule("additionalProperties", field)
	ref = schema.get("$ref")
	if ref:
		if ref in refs:
			raise UnsupportedSchemaRule("$ref (recursive schema)", field)
		refs = refs | {ref}
	for key, sub in (schema.get("properties") or {}).items():
		_check_rules(sub, f"{path}.{key}" if path else key, refs)
	if isinstance(schema.get("items"), dict):
		_check_rules(schema["items"], f"{path}[]", refs)
	for combinator in ("anyOf", "oneOf", "allOf"):
		for sub in schema.get(combinator) or []:
			_check_rules(sub, path, refs)
	for sub in (schema.get("$defs") or schema.get("definitions") or {}).values():
		_check_rules(sub, path, refs)


def provider_schema(schema: dict) -> dict:
	"""The schema as sent to a native JSON mode: every object closed, and no rule a provider rejects.

	The reply is still checked against the author's schema, so a dropped rule is enforced locally.
	"""
	out = {key: value for key, value in schema.items() if key not in _UNSUPPORTED_RULES}
	if out.get("type") == "object" or "properties" in out:
		out.setdefault("additionalProperties", False)
	if isinstance(out.get("properties"), dict):
		out["properties"] = {key: _provider(sub) for key, sub in out["properties"].items()}
	if isinstance(out.get("items"), dict):
		out["items"] = provider_schema(out["items"])
	for combinator in ("anyOf", "oneOf", "allOf"):
		if isinstance(out.get(combinator), list):
			out[combinator] = [_provider(sub) for sub in out[combinator]]
	for defs in ("$defs", "definitions"):
		if isinstance(out.get(defs), dict):
			out[defs] = {key: _provider(sub) for key, sub in out[defs].items()}
	return out


def _provider(sub: Any) -> Any:
	return provider_schema(sub) if isinstance(sub, dict) else sub


def all_fields_required(schema: Any) -> bool:
	"""True when every object lists all its properties as required, which OpenAI strict mode needs."""
	if not isinstance(schema, dict):
		return True
	properties = schema.get("properties")
	if isinstance(properties, dict):
		if set(properties) - set(schema.get("required") or []):
			return False
		if not all(all_fields_required(sub) for sub in properties.values()):
			return False
	if not all_fields_required(schema.get("items")):
		return False
	return all(all_fields_required(sub) for c in ("anyOf", "oneOf", "allOf") for sub in schema.get(c) or [])


def anthropic_output_config(schema: dict) -> dict:
	return {"format": {"type": "json_schema", "schema": schema}}


def openai_response_format(schema: dict) -> dict:
	"""Strict when the schema allows it; strict mode refuses a schema with optional fields."""
	return {
		"type": "json_schema",
		"json_schema": {"name": "response", "schema": schema, "strict": all_fields_required(schema)},
	}


def system_prompt_with_format(system_prompt: str, schema: dict, native: bool) -> str:
	"""The system prompt plus the field line, and the full schema when the model has no JSON mode."""
	lines = []
	if not native:
		lines.append(
			"Reply with only one JSON object that matches this JSON Schema, with nothing before or after it:"
		)
		lines.append(json.dumps(schema, indent=2))
	fields = ", ".join((schema.get("properties") or {}).keys())
	if fields:
		lines.append(
			f"The reply has these fields: {fields}. A field that does not apply is left empty, or null where its type allows, never left out."
		)
	note = "\n".join(lines)
	return f"{system_prompt}\n\n{note}" if system_prompt else note


def retry_note(error: str) -> str:
	return f"Your previous reply did not match the required JSON format: {error}. Reply again with only the corrected JSON object."


def read_json_reply(text: str, schema: dict | None, stop_reason: str | None = None) -> Any:
	"""Parse and check a reply. Raises ReplyRejected; a cut-off or refused reply is never parsed."""
	if stop_reason in _LENGTH_STOPS:
		raise ReplyRejected(
			f"the reply was cut off at the output token limit (stop reason '{stop_reason}') "
			"before the JSON was complete; raise Max Tokens",
			retry=False,
		)
	if stop_reason in _SAFETY_STOPS:
		raise ReplyRejected(
			f"the model refused or was blocked (stop reason '{stop_reason}'), so no JSON came back",
			retry=False,
		)

	body = strip_code_fences(text)
	try:
		parsed = json.loads(body)
	except json.JSONDecodeError as exc:
		parsed = extract_json_object(body)
		if parsed is None:
			raise ReplyRejected(f"the reply is not valid JSON ({exc})", retry=True) from exc

	if schema:
		try:
			import jsonschema
		except ImportError as exc:
			raise ReplyRejected(
				"the jsonschema package is not installed, so the reply cannot be checked against the response schema",
				retry=False,
			) from exc
		try:
			jsonschema.validate(parsed, schema)
		except jsonschema.ValidationError as exc:
			raise ReplyRejected(_schema_error(exc), retry=True) from exc
	return parsed


def _schema_error(exc) -> str:
	if exc.validator == "required":
		return f"missing required field {exc.message.split(' is a required property')[0]}"
	where = ".".join(str(p) for p in exc.absolute_path)
	return f"{exc.message} (field '{where}')" if where else exc.message


def strip_code_fences(content: str) -> str:
	"""The text inside a surrounding Markdown code fence, or the text itself."""
	text = (content or "").strip()
	if text.startswith("```"):
		newline = text.find("\n")
		text = text[newline + 1 :] if newline != -1 else text[3:]
		if text.rstrip().endswith("```"):
			text = text.rstrip()[:-3]
	return text.strip()


def extract_json_object(text: str) -> dict | None:
	"""The first JSON object embedded in surrounding prose, or None."""
	decoder = json.JSONDecoder()
	idx = text.find("{")
	while idx != -1:
		try:
			obj, _end = decoder.raw_decode(text, idx)
		except json.JSONDecodeError:
			idx = text.find("{", idx + 1)
			continue
		if isinstance(obj, dict):
			return obj
		idx = text.find("{", idx + 1)
	return None
