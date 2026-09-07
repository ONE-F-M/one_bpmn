# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""Move the BA Agent's private planning checkpoint into Chat Session State.

The BA Agent kept its accumulated plan in ``Chat Conversation State``, a
onefm_mcp doctype holding one JSON blob per conversation. Its own Save Response
script carried the note "Retiring Chat Conversation State is a separate story";
this is that story.

The replacement is better on the things that matter here rather than merely
newer: entries are rows, so a plan is queryable by key instead of buried in a
blob; and it carries a version, so two overlapping turns cannot silently
overwrite one another's checkpoint — which the old doctype had no defence
against at all.

Only rows whose conversation still exists are migrated. The rest are orphans
pointing at conversations that were deleted, and carrying them across would
import rubbish into a new table on day one.

The old rows are LEFT IN PLACE. Dropping them is a one-way operation on real
data and belongs behind a human decision, not inside a migration that runs on
every site automatically.
"""

import json

import frappe

SOURCE = "Chat Conversation State"
TARGET = "Chat Session State"


def execute():
	if not frappe.db.exists("DocType", SOURCE) or not frappe.db.exists("DocType", TARGET):
		return

	rows = frappe.get_all(
		SOURCE,
		fields=["name", "conversation", "current_mode", "iteration", "state_data"],
		limit_page_length=0,
	)
	if not rows:
		return

	from one_bpmn.agents.memory.session_state import set_state

	migrated = skipped = failed = 0
	for row in rows:
		conversation = row.get("conversation")
		if not conversation or not frappe.db.exists("Chat Conversation", conversation):
			skipped += 1
			continue
		if frappe.db.exists(TARGET, conversation):
			# Something already wrote a scratchpad for this conversation. It is
			# newer than this checkpoint by definition, so it wins.
			skipped += 1
			continue

		values = _values_from(row)
		if not values:
			skipped += 1
			continue
		try:
			set_state(conversation, values)
			migrated += 1
		except Exception:
			failed += 1
			frappe.log_error(
				title="BA state migration: could not migrate a checkpoint",
				message=f"{SOURCE}={row['name']} conversation={conversation}\n"
				f"{frappe.get_traceback()}",
			)

	frappe.db.commit()
	print(
		f"BA planning state -> {TARGET}: {migrated} migrated, "
		f"{skipped} skipped (orphaned or already present), {failed} failed. "
		f"Source rows left in place."
	)


def _values_from(row: dict) -> dict:
	"""The blob's keys become entries; the columns beside it come across too.

	A blob that will not parse is carried over whole under one key rather than
	dropped — it is somebody's plan, and losing it silently during a migration
	would be worse than storing it in a shape nothing reads yet.
	"""
	values = {}
	raw = (row.get("state_data") or "").strip()
	if raw:
		try:
			parsed = json.loads(raw)
			if isinstance(parsed, dict):
				values.update(parsed)
			else:
				values["state_data"] = parsed
		except (ValueError, TypeError):
			values["state_data"] = raw

	if row.get("current_mode"):
		values.setdefault("stage", row["current_mode"])
	if row.get("iteration"):
		values["iteration"] = row["iteration"]
	return values
