# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""ONE-FM AG-UI extension event contract (WI-001671).

The contract is DATA — ``schemas/events.json`` — mirroring the WI-001649
payload-contract style: schemas and examples live in the repo, never prose
baked into prompts or components. This module is the thin accessor: load,
list, validate. The conformance suite (WI-001680) and the frontend card
registry (WI-001673) both key off the same file.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

_SCHEMAS_PATH = Path(__file__).parent / "schemas" / "events.json"

EVENT_NAMESPACE = "onefm."


@lru_cache(maxsize=1)
def _contract() -> dict:
	with open(_SCHEMAS_PATH) as f:
		return json.load(f)


def list_events() -> list[str]:
	"""Every contract event name, sorted."""
	return sorted(_contract()["events"].keys())


def get_event(name: str) -> dict | None:
	"""The full contract entry (producers, schema, example, notes) or None."""
	return _contract()["events"].get(name)


def get_schema(name: str) -> dict | None:
	entry = get_event(name)
	return entry.get("schema") if entry else None


def is_contract_event(name: str) -> bool:
	return name in _contract()["events"]


def validate_event(name: str, value: dict) -> list[str]:
	"""Validate a CustomEvent value against its contract schema.

	Returns a list of human-readable problems — empty when valid. An
	unknown ``onefm.*`` name is itself a violation (the conformance suite
	fails the build on it); non-namespaced names are not ours to judge.
	"""
	problems: list[str] = []
	if not name.startswith(EVENT_NAMESPACE):
		problems.append(
			f"custom event name '{name}' is outside the {EVENT_NAMESPACE}* namespace"
		)
		return problems
	schema = get_schema(name)
	if schema is None:
		problems.append(f"unknown contract event '{name}' — not in schemas/events.json")
		return problems

	import jsonschema

	validator = jsonschema.Draft202012Validator(schema)
	for error in validator.iter_errors(value):
		path = "/".join(str(p) for p in error.absolute_path) or "<root>"
		problems.append(f"{name}: {path}: {error.message}")
	return problems


def validate_examples() -> list[str]:
	"""Every example in the contract must satisfy its own schema."""
	problems: list[str] = []
	for name, entry in _contract()["events"].items():
		problems.extend(validate_event(name, entry.get("example", {})))
	return problems
