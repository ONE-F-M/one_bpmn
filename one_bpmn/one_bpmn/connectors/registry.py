# Copyright (c) 2026, one-fm and contributors
# Connector registry — maps (connectorId, operation) to a Python handler.
#
# A handler has signature ``handler(params: dict, ctx: dict) -> dict``:
#   params — resolved (Jinja-rendered + link/ID-normalized) operation inputs
#   ctx    — {"instance", "task", "doc", "task_data"}
# Its return value (a JSON-safe dict) is written to task.data[resultVariable].
#
# This is the runtime analogue of Camunda's job-type → worker binding: the
# service task's (connectorId, operation) is the dispatch key.

CONNECTORS = {}


def connector(connector_id, operation):
    """Decorator registering a handler for a (connectorId, operation) pair."""

    def deco(fn):
        CONNECTORS.setdefault(connector_id, {})[operation] = fn
        return fn

    return deco


def get_handler(connector_id, operation):
    """Return the handler for (connectorId, operation), or None."""
    return CONNECTORS.get(connector_id, {}).get(operation)


def registered():
    """{connectorId: [operation, ...]} — for diagnostics/tests."""
    return {cid: sorted(ops) for cid, ops in CONNECTORS.items()}
