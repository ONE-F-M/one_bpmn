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


def validate_stream(chunks: list, agent_id: str = "") -> list[str]:
	"""Validate one turn's encoded SSE chunks as a conformant AG-UI stream
	(WI-001680). Returns human-readable problems, each naming the agent and
	the offending event — empty when conformant.

	Rules enforced:
	* RUN_STARTED is the first event; nothing precedes it.
	* Exactly one terminal RUN_FINISHED, and it is the last event.
	* At most one RUN_ERROR, and only before the terminal event.
	* Every CUSTOM event name is namespaced ``onefm.*`` and validates
	  against its contract schema.
	"""
	who = f"[{agent_id}] " if agent_id else ""
	events = []
	for chunk in chunks:
		for line in str(chunk).splitlines():
			if line.startswith("data: "):
				try:
					events.append(json.loads(line[len("data: ") :]))
				except Exception:
					events.append({"type": "__UNPARSEABLE__", "raw": line[:120]})

	problems: list[str] = []
	if not events:
		return [f"{who}stream produced no events"]

	types = [(e.get("type") or "").upper() for e in events]
	if types[0] != "RUN_STARTED":
		problems.append(f"{who}first event is {types[0]}, expected RUN_STARTED")
	if types.count("RUN_STARTED") != 1:
		problems.append(f"{who}{types.count('RUN_STARTED')} RUN_STARTED events, expected exactly 1")
	if types.count("RUN_FINISHED") != 1:
		problems.append(f"{who}{types.count('RUN_FINISHED')} RUN_FINISHED events, expected exactly 1")
	elif types[-1] != "RUN_FINISHED":
		problems.append(f"{who}last event is {types[-1]}, expected RUN_FINISHED")
	if types.count("RUN_ERROR") > 1:
		problems.append(f"{who}{types.count('RUN_ERROR')} RUN_ERROR events, expected at most 1")
	if "__UNPARSEABLE__" in types:
		problems.append(f"{who}stream carried an unparseable data line")

	for event in events:
		if (event.get("type") or "").upper() != "CUSTOM":
			continue
		name = event.get("name") or ""
		for problem in validate_event(name, event.get("value") or {}):
			problems.append(f"{who}{problem}")
	return problems
