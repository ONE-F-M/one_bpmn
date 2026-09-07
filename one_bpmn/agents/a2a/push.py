# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""Push notifications for A2A tasks — both directions (WI-001933).

Polling is the floor: it needs nothing open to the internet and works
against a partner with no callback support. But its interval widens to a
cap, so a task that finishes just after a check waits out the rest of the
interval. For work that runs for hours that staleness is the real cost,
and a callback removes it.

So push is layered ON TOP of polling, never instead of it:

- **Outbound** — when a remote's card says it can push, we register a
  callback carrying a per-task secret, and polling drops back to a slow
  reconciliation. A dropped callback then costs latency, not a hung
  process. Push-only would be a single point of failure.
- **Inbound** — a caller may register their own callback with us, and we
  POST the task to them when it reaches a state they care about. Delivery
  is best-effort by design: the caller can always poll, so a dead
  callback URL must never fail the agent's actual work.

The callback endpoint is reachable without a Frappe session (the remote
has no user here), which makes the per-task token the entire gate — hence
the constant-time compare, the forward-only state rule, and the refusal
to say anything about tasks whose token does not match.
"""

from __future__ import annotations

import hmac

import frappe
from frappe.utils import get_url

from one_bpmn.agents import a2a_contract

# Interval used instead of the polling backoff once a remote has agreed to
# push. Long enough that reconciliation is cheap, short enough that a lost
# callback is noticed the same working hour.
PUSH_RECONCILE_SECONDS = 1800

# The states worth waking someone for. Intermediate "working" churn is not
# pushed — a caller who wants progress detail can poll.
NOTIFY_STATES = frozenset(a2a_contract.terminal_states() | {"input-required"})

TOKEN_HEADER = "X-A2A-Notification-Token"

# The callback endpoint is guest-reachable, so it gets its own throttle per
# source address. Done here rather than with the framework decorator because
# that one needs a real request IP and would break every test that exercises
# the endpoint directly.
CALLBACK_RATE_LIMIT = 120
CALLBACK_RATE_WINDOW = 60

# After this many consecutive delivery failures we stop trying. The caller
# still has polling, and a dead URL must not become an unbounded retry loop.
MAX_PUSH_FAILURES = 5


def callback_url() -> str:
	"""Where remotes should call us back."""
	return get_url("/api/method/one_bpmn.api.a2a_api.push_callback")


def mint_token() -> str:
	return frappe.generate_hash(length=48)


def remote_supports_push(remote) -> bool:
	"""Whether a registry entry's cached card advertises push."""
	card = frappe.parse_json(remote.agent_card or "{}") or {}
	return bool((card.get("capabilities") or {}).get("pushNotifications"))


def callback_throttled() -> bool:
	"""Whether this source address has exceeded the callback rate. Never
	raises, and is a no-op when there is no request IP to key on."""
	ip = getattr(frappe.local, "request_ip", None)
	if not ip:
		return False
	key = f"a2a_push_cb:{ip}"
	try:
		count = frappe.utils.cint(frappe.cache.get_value(key)) + 1
		frappe.cache.set_value(key, count, expires_in_sec=CALLBACK_RATE_WINDOW)
		return count > CALLBACK_RATE_LIMIT
	except Exception:
		return False


def token_matches(task, presented: str | None) -> bool:
	"""Constant-time compare against the task's own secret."""
	if not presented:
		return False
	expected = task.get_password("callback_token", raise_exception=False)
	if not expected:
		return False
	return hmac.compare_digest(str(expected), str(presented))


def register_with_remote(task, remote) -> bool:
	"""Ask a remote to call us when this task changes. Returns whether it
	agreed. Never raises: failing to register is not failing to delegate —
	we simply keep polling."""
	from one_bpmn.one_bpmn.integrations import a2a_client

	if not (task.remote_task_id and remote_supports_push(remote)):
		return False

	token = mint_token()
	try:
		a2a_client.set_push_config(remote, task.remote_task_id, callback_url(), token)
	except Exception:
		frappe.log_error(
			title=f"A2A push registration declined ({remote.name}) — falling back to polling",
			message=frappe.get_traceback(),
		)
		return False

	task.db_set(
		{"callback_token": token, "push_registered": 1},
		update_modified=False,
	)
	task.reload()
	return True


def store_caller_config(task, config: dict) -> None:
	"""Inbound: remember where this caller wants to be told. The URL gets
	the same SSRF treatment as any outbound address, because we will be the
	ones calling it."""
	from one_bpmn.one_bpmn.connectors.http_ops import _assert_host_allowed

	if not config:
		return  # no config offered — polling stays the caller's only route
	problems = a2a_contract.validate("push_notification_config", config)
	if problems:
		from one_bpmn.agents.a2a.protocol import A2AError, log_validation_failure

		log_validation_failure("input", problems, content=frappe.as_json(config))
		raise A2AError("INVALID_PARAMS", "pushNotificationConfig failed schema validation", data=problems)

	# A caller must not be able to point us at the internal network.
	url = config["url"]
	_assert_host_allowed(url, allow_internal=bool(frappe.conf.get("a2a_allow_internal_callbacks")))

	values = {"push_callback_url": url}
	if config.get("token"):
		values["push_callback_token"] = config["token"]
	task.db_set(values, update_modified=False)
	task.reload()


def notify_caller(task) -> None:
	"""Inbound: POST the task to the caller's callback. Best-effort — the
	caller can always poll, so nothing here may raise into the agent's work."""
	if task.direction != "Inbound" or not task.push_callback_url:
		return
	if task.state not in NOTIFY_STATES:
		return
	if frappe.utils.cint(task.push_failures) >= MAX_PUSH_FAILURES:
		return

	from one_bpmn.agents.a2a.protocol import task_to_wire
	from one_bpmn.one_bpmn.connectors.http_ops import _assert_host_allowed
	from one_bpmn.one_bpmn.integrations.a2a_client import _session

	try:
		_assert_host_allowed(
			task.push_callback_url,
			allow_internal=bool(frappe.conf.get("a2a_allow_internal_callbacks")),
		)
		headers = {"Content-Type": "application/json"}
		token = task.get_password("push_callback_token", raise_exception=False)
		if token:
			headers[TOKEN_HEADER] = token
		response = _session().post(
			task.push_callback_url, json=task_to_wire(task), timeout=10, headers=headers
		)
		response.raise_for_status()
		if frappe.utils.cint(task.push_failures):
			task.db_set("push_failures", 0, update_modified=False)
	except Exception:
		failures = frappe.utils.cint(task.push_failures) + 1
		task.db_set("push_failures", failures, update_modified=False)
		frappe.log_error(
			title=f"A2A push delivery failed ({task.name}, attempt {failures})",
			message=frappe.get_traceback(),
		)
