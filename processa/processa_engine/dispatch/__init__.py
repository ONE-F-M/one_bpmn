# Copyright (c) 2026, one-fm and contributors
"""Service Task actions, one module each; every dispatcher takes the instance doc, the task and its config."""

from processa.processa_engine.dispatch import (
	ai_agent,
	common,
	connector,
	email,
	google_chat,
	push_notification,
	send_notification,
	update_field,
)

__all__ = [
	"ai_agent",
	"common",
	"connector",
	"email",
	"google_chat",
	"push_notification",
	"send_notification",
	"update_field",
]
