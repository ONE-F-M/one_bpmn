# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""
AI Injection Pattern — the prompt-injection rule pack, held as data (WI-001967).

A rule is a row, so adding one, tightening one, or switching one off is an edit
in the desk rather than a code change and a deploy. That is the whole point: the
pack has to move at the speed of the attacks, not the release train.

Two things this controller guarantees, because a bad row here would otherwise
surface as a runtime failure inside screening:

  * a regex rule must compile, checked on save;
  * the active pack is cached, so screening every message does not become a
    query per message.
"""

import re

import frappe
from frappe import _
from frappe.model.document import Document

CACHE_KEY = "ai_injection_pattern_pack"


class AIInjectionPattern(Document):
	def validate(self):
		self.pattern_name = (self.pattern_name or "").strip()
		self.pattern = (self.pattern or "").strip()
		if not self.pattern:
			frappe.throw(_("Pattern is required."))

		if self.match_mode == "regex":
			try:
				re.compile(self.pattern, re.IGNORECASE)
			except re.error as exc:
				frappe.throw(
					_("Pattern is not a valid regular expression: {0}").format(exc),
					title=_("Invalid Pattern"),
				)

	def on_update(self):
		clear_pattern_cache()

	def after_delete(self):
		clear_pattern_cache()


def clear_pattern_cache() -> None:
	frappe.cache().delete_value(CACHE_KEY)


def active_patterns(boundary: str | None = None) -> list[dict]:
	"""Enabled rules, cached, optionally narrowed to one boundary.

	Returns plain dicts rather than documents — screening runs on every message
	and does not need the document machinery. Never raises: an unreadable pack
	means no rules fired, which is the same failure mode as an empty pack, and
	is far better than taking down the conversation.
	"""
	try:
		rows = frappe.cache().get_value(CACHE_KEY)
		if rows is None:
			rows = frappe.get_all(
				"AI Injection Pattern",
				filters={"enabled": 1},
				fields=[
					"name",
					"pattern_name",
					"pattern",
					"match_mode",
					"pattern_type",
					"severity",
					"action",
					"boundary_scope",
					"source_taxonomy",
				],
				order_by="severity desc, pattern_name asc",
				limit_page_length=0,
			)
			rows = [dict(r) for r in rows]
			frappe.cache().set_value(CACHE_KEY, rows)
	except Exception:
		return []

	if not boundary:
		return rows
	return [r for r in rows if r.get("boundary_scope") in ("any", boundary)]


def compile_rule(rule: dict):
	"""Compiled matcher for one rule, or None when it cannot be compiled.

	Substring rules are compiled too (escaped), so callers have one code path.
	"""
	pattern = (rule.get("pattern") or "").strip()
	if not pattern:
		return None
	try:
		if rule.get("match_mode") == "substring":
			return re.compile(re.escape(pattern), re.IGNORECASE)
		return re.compile(pattern, re.IGNORECASE)
	except re.error:
		# Validation blocks this on save, but a row edited straight in the DB
		# must not break screening for every message that follows.
		return None
