# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""A2A wire contract (WI-001931).

The contract is DATA — ``schemas/a2a.json`` — mirroring the AG-UI
contract style: schemas, states and error codes live in the repo, never
prose baked into code. This module is the thin accessor: load, look up,
validate. Both sides of the protocol key off the same file — the server
(``agents/a2a/protocol.py``) validates inbound envelopes against it, the
client (``integrations/a2a_client.py``) validates outbound ones
(WI-002009), and the card test validates our own Agent Card.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

_SCHEMAS_PATH = Path(__file__).parent / "schemas" / "a2a.json"


@lru_cache(maxsize=1)
def _contract() -> dict:
	with open(_SCHEMAS_PATH) as f:
		return json.load(f)


PROTOCOL_VERSION: str = json.loads(_SCHEMAS_PATH.read_text())["protocolVersion"]


def a2a_states() -> list[str]:
	return list(_contract()["states"])


def terminal_states() -> set[str]:
	return set(_contract()["terminalStates"])


def error_code(name: str) -> int:
	"""A named JSON-RPC / A2A error code, e.g. error_code("TASK_NOT_FOUND")."""
	return _contract()["errorCodes"][name]


def trace_key(name: str) -> str:
	"""Metadata key carrying delegation trace data (WI-002008):
	taskExecutionId, delegationDepth or handoffCount."""
	return _contract()["traceMetadataKeys"][name]


def get_schema(name: str) -> dict | None:
	return _contract()["schemas"].get(name)


def validate(name: str, value: dict) -> list[str]:
	"""Validate a wire object against a named contract schema. Returns
	human-readable problems — empty when valid (WI-002009)."""
	schema = get_schema(name)
	if schema is None:
		return [f"unknown contract schema '{name}'"]

	import jsonschema

	problems: list[str] = []
	validator = jsonschema.Draft202012Validator(schema)
	for error in validator.iter_errors(value):
		path = "/".join(str(p) for p in error.absolute_path) or "<root>"
		problems.append(f"{name}: {path}: {error.message}")
	return problems
