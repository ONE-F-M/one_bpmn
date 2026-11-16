# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""Move the connection off AI Provider and onto AI Model.

AI Provider is now a single Data field. Everything that made it a connection —
the dialect, the endpoint, the key, the on/off switch — belongs to the model, so
this carries that data down before the columns are dropped and nothing can read
it again.

WHAT THE NAME NOW HAS TO CARRY
------------------------------
With provider_type gone, the record's NAME is the only thing left that says
which API dialect it speaks, so a provider has to be named for what it speaks.
"Test Provider" is an OpenAI connection with seven models hanging off it and a
name that routes nowhere, so it is renamed to "OpenAI" — the models follow the
rename, because provider is a Link.

Two duplicate Anthropic connections go with it. A name that IS the dialect
cannot be held twice, and neither had a model or an agent pointing at it. One of
them holds a real key, so its fingerprint is printed before it is destroyed:
this is not recoverable, and a line in the migrate log is the only trace left.

THE KEY IS COPIED, NOT MOVED
----------------------------
One provider key served every model beneath it. Each of those models now gets
its own copy, so nothing stops working the moment the provider column goes.
The cost is real and worth stating: rotating the Anthropic key is now six edits
rather than one. That is what holding the connection per model means.

Only fills what is empty — a model that already carries its own key keeps it.
"""

import hashlib

import frappe
from frappe.utils.password import get_decrypted_password, set_encrypted_password

# Provider records renamed so their name states the dialect.
RENAMES = {"Test Provider": "OpenAI"}

# Duplicate connections. A dialect cannot be held twice.
REMOVE = ("Anthropic 2", "Anthropic Sonnet")

# Columns that described a connection.
DROPPED_COLUMNS = ("provider_type", "enabled", "api_endpoint", "api_key")

# Model id prefix -> the provider that made it. Deliberately duplicated rather
# than imported from a later patch: a patch must not break when a different one
# is edited.
BY_PREFIX = (
	("claude-", "Anthropic"),
	("gpt-", "OpenAI"),
	("o1-", "OpenAI"),
	("o3-", "OpenAI"),
	("o4-", "OpenAI"),
	("gemini-", "Google"),
)


def _adopt_orphans():
	"""Attach a provider-less model to an EXISTING provider named by its id.

	This has to run before the key moves, and the reason is production. Its
	models carry no credential link and no agent names one, so nothing upstream
	could attach them -- they arrive here orphaned. Copying the key "onto every
	model beneath a provider" would then find nothing beneath the one provider
	that has a key, and the very next step drops the column and the __Auth row.
	The site's only API key would be destroyed with nothing carrying it forward.

	Only onto providers that already exist. Creating the missing ones is the
	catalogue patch's job, and a provider invented here would have no key to give
	anyway.
	"""
	for row in frappe.get_all("AI Model", filters={"provider": ["in", ["", None]]}, fields=["name"]):
		for prefix, provider in BY_PREFIX:
			if row.name.startswith(prefix) and frappe.db.exists("AI Provider", provider):
				frappe.db.set_value("AI Model", row.name, "provider", provider,
				                    update_modified=False)
				print(f"AI Model: {row.name} had no provider; its id says {provider}")
				break


def _fingerprint(key: str) -> str:
	return f"{key[:12]}…{key[-4:]} len={len(key)} sha256={hashlib.sha256(key.encode()).hexdigest()[:16]}"


def _copy_connection_down():
	"""Give every model the key and endpoint of the provider it sits under."""
	if not frappe.db.has_column("AI Provider", "api_key"):
		return

	for provider in frappe.get_all("AI Provider", pluck="name"):
		key = get_decrypted_password("AI Provider", provider, "api_key", raise_exception=False)
		endpoint = frappe.db.get_value("AI Provider", provider, "api_endpoint")
		if not key and not endpoint:
			continue

		for model in frappe.get_all("AI Model", filters={"provider": provider}, pluck="name"):
			if endpoint and not frappe.db.get_value("AI Model", model, "api_endpoint"):
				frappe.db.set_value("AI Model", model, "api_endpoint", endpoint, update_modified=False)
			if key and not get_decrypted_password("AI Model", model, "api_key", raise_exception=False):
				set_encrypted_password("AI Model", model, key, "api_key")
			print(f"AI Model: {model} took the connection from provider {provider}")


def _rename_for_dialect():
	for old, new in RENAMES.items():
		if not frappe.db.exists("AI Provider", old) or frappe.db.exists("AI Provider", new):
			continue
		# Models point at the provider by Link, so Frappe carries them across.
		# frappe.rename_doc is a narrower wrapper than the function it calls and
		# takes no ignore_permissions, so this goes to the real one.
		from frappe.model.rename_doc import rename_doc

		rename_doc("AI Provider", old, new, force=True, ignore_permissions=True,
		           show_alert=False)
		frappe.db.set_value("AI Provider", new, "provider", new, update_modified=False)
		print(f"AI Provider: renamed {old} to {new} so its name states its dialect")


def _remove_duplicates():
	for name in REMOVE:
		if not frappe.db.exists("AI Provider", name):
			continue
		# Never delete one something still points at, whatever the plan said.
		if frappe.db.count("AI Model", {"provider": name}) or frappe.db.count(
			"AI Agent Configuration", {"ai_provider": name}
		):
			print(f"AI Provider: kept {name} — something still references it")
			continue

		key = get_decrypted_password("AI Provider", name, "api_key", raise_exception=False)
		if key:
			print(f"AI Provider: destroying the key on {name} — {_fingerprint(key)}")
		frappe.delete_doc("AI Provider", name, force=True, ignore_permissions=True,
		                  delete_permanently=True)
		print(f"AI Provider: removed duplicate {name}")


def _drop_columns():
	for column in DROPPED_COLUMNS:
		if frappe.db.has_column("AI Provider", column):
			frappe.db.sql_ddl(f"ALTER TABLE `tabAI Provider` DROP COLUMN `{column}`")
	frappe.db.sql("DELETE FROM `__Auth` WHERE doctype = %s", ("AI Provider",))


def execute():
	if not frappe.db.exists("DocType", "AI Provider") or not frappe.db.exists("DocType", "AI Model"):
		return
	# The destination has to exist before anything is carried into it.
	if not frappe.db.has_column("AI Model", "api_key"):
		frappe.log_error(
			title="AI connection move skipped",
			message="AI Model has no api_key column yet; run migrate again after the doctype syncs.",
		)
		return

	# Before the copy, not after: an orphaned model gets no key, and the copy is
	# the last moment the key exists to be copied.
	_adopt_orphans()
	_copy_connection_down()
	frappe.db.commit()

	_rename_for_dialect()
	_remove_duplicates()
	frappe.db.commit()

	_drop_columns()
	frappe.db.commit()
	frappe.clear_cache()
