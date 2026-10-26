"""
Shared precedence chain for picking a memory model (WI-002168).

Both the dispatch path (``dispatchers._memory_model``, resolving what to run)
and the config-time path (``AI Agent Configuration.validate()``/its "effective
model" preview, resolving what *will* run before anything is dispatched) must
agree on the same three-step fallback, or the admin-visible answer can diverge
from the runtime one. This is the one place that chain is written.
"""

from __future__ import annotations

import frappe


def resolve_memory_model(own_value: str | None, settings_field: str, fallback_value: str | None) -> str | None:
	"""Resolve a memory model in precedence order (WI-001793, WI-002168).

	1. ``own_value`` — the agent's own field (distill/reconcile model).
	2. The site-wide ``Processa Settings.<settings_field>`` default.
	3. ``fallback_value`` — the agent's own chat model (``ai_model``/``config.model``).

	Returns ``None`` if nothing in the chain resolves — callers decide what
	that means for them (dispatch degrades gracefully; config validation
	treats it as unresolvable and blocks).
	"""
	model = own_value.strip() if isinstance(own_value, str) else own_value
	if model:
		return model

	if settings_field:
		try:
			default = frappe.db.get_single_value("Processa Settings", settings_field)
			if default:
				return default
		except Exception:
			# A missing/unreadable setting must never break this resolution.
			pass

	return fallback_value or None
