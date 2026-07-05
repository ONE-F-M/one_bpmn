"""Convenience helpers for building token-enriched action dicts.

When composing an email for a BPMN task, the caller passes raw actions
like ``[{"label": "Approve", "url": "…", "primary": True}]``.  This
module enriches each action with an HMAC token so that the AMP template
can render secure ``\u003cform action-xhr\u003e`` submissions instead of plain links.

Usage::

	from one_bpmn.email_builder.email_actions import build_email_actions

	actions = build_email_actions(
		instance_name="BPMN-INST-001",
		task_id="uuid-...",
		actions=[
			{"label": "Approve", "url": "…", "primary": True},
			{"label": "Reject",  "url": "…", "primary": False},
		],
		user="manager@one-fm.com",
	)
	# Each dict now has an added "token" key
"""

from __future__ import annotations

from one_bpmn.utils.token import generate_action_token


def build_email_actions(
	instance_name: str,
	task_id: str,
	actions: list[dict],
	user: str,
	expiry_hours: int = 72,
) -> list[dict]:
	"""Enrich action dicts with HMAC tokens for AMP email.

	Takes a list of action dicts (each with at least ``label``) and
	returns new dicts with an added ``token`` field.

	Args:
		instance_name: BPMN Process Instance document name.
		task_id: SpiffWorkflow task UUID.
		actions: List of action dicts, each having at minimum a
			``label`` key.  May also have ``url`` and ``primary``.
		user: Frappe user (email) allowed to execute the action.
		expiry_hours: Token validity in hours (default 72).

	Returns:
		A new list of action dicts, each with an added ``token`` key.
		Original dicts are not mutated.
	"""
	enriched = []
	for action in actions:
		# Use the label as the action name for the token
		action_name = action.get("label", "")
		token = generate_action_token(
			instance_name=instance_name,
			task_id=task_id,
			action=action_name,
			user=user,
			expiry_hours=expiry_hours,
		)
		enriched.append({
			**action,
			"token": token,
			"instance_name": instance_name,
			"task_id": task_id,
			"action_name": action_name,
		})
	return enriched
