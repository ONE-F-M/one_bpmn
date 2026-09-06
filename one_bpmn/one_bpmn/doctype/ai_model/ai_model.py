# Copyright (c) 2026, Samdani Kouser and contributors
# For license information, please see license.txt
"""
AI Model — a catalogue entry that also carries the connection.

Since WI-002134 the key, endpoint and on/off switch live on the model. That
makes this record the one place a broken credential can be caught before an
agent finds it (WI-002191):

* an enabled model must name a provider and hold a key — the form already asks
  for both, but only the server can refuse a save that lacks them;
* a key that is new or changed is tried against the provider before the save
  goes through, so a typo is a form error and not four days of failed runs;
* the ``health_*`` fields record what the last check, run or probe found. They
  are written by :mod:`one_bpmn.agents.model_health`, never by the form.

A save proves the key works or does not. A provider that merely cannot be
reached right now proves nothing, so that saves with a warning and leaves the
scheduled probe to confirm.
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint
from frappe.utils.password import get_decrypted_password


class AIModel(Document):
	def validate(self):
		self._keep_platform_health_fields()
		if not cint(self.enable_model):
			return
		if not (self.provider or "").strip():
			frappe.throw(
				_(
					"An enabled model must name its AI Provider — the provider is what "
					"routes a call, so a model without one can never be dispatched."
				),
				title=_("Provider required"),
			)
		if not self._has_key():
			frappe.throw(
				_(
					"An enabled model needs an API key. Enter the {0} key on this record, "
					"or untick Enable Model."
				).format(self.provider),
				title=_("API key required"),
			)
		self._probe_on_save()

	def on_update(self):
		from one_bpmn.agents import model_health

		if not cint(self.enable_model):
			model_health.clear_health(self.name)
			return
		result = self.flags.get("credential_probe")
		if result and result.get("ok"):
			# The key is in __Auth by now (written in db_insert/db_update), so
			# the row this creates describes the stored credential.
			model_health.record_success(self.name, source="Save")

	# ------------------------------------------------------------------

	def _keep_platform_health_fields(self):
		"""The health_* fields are the platform's, not the form's. A form sends
		back the values it loaded, so a save made after a run marked the model
		Unhealthy would quietly reset it — the stored values win."""
		if self.is_new():
			return
		stored = frappe.db.get_value(
			"AI Model", self.name, [f for f in self.meta.get_valid_columns() if f.startswith("health_")],
			as_dict=True,
		)
		for field, value in (stored or {}).items():
			self.set(field, value)

	def _has_key(self) -> bool:
		"""A key typed into the form, or one already stored for this record."""
		if (self.api_key or "").strip():
			return True
		if self.is_new():
			return False
		return bool(get_decrypted_password("AI Model", self.name, "api_key", raise_exception=False))

	def _key_changed(self) -> bool:
		"""A real value in the field, rather than the ***** mask the form sends
		back when the key was left alone."""
		return bool(self.api_key) and not self.is_dummy_password(self.api_key)

	def _probe_on_save(self):
		"""Try the credentials against the provider when something about the
		connection changed. Blocks on a rejected key; warns on an unreachable
		provider; silent when nothing relevant changed."""
		flags = frappe.flags
		if flags.in_migrate or flags.in_install or flags.in_patch or flags.skip_ai_model_probe:
			return
		if flags.in_test and not flags.ai_model_probe_in_test:
			return

		before = self.get_doc_before_save()
		key_changed = self._key_changed()
		newly_enabled = before is None or not cint(before.enable_model)
		connection_changed = before is not None and (
			(before.api_endpoint or "") != (self.api_endpoint or "")
			or (before.provider or "") != (self.provider or "")
		)
		if not (key_changed or newly_enabled or connection_changed):
			return

		from one_bpmn.agents import model_health

		key = (
			self.api_key
			if key_changed
			else get_decrypted_password("AI Model", self.name, "api_key", raise_exception=False) or ""
		)
		result = model_health.probe_credentials(self.provider, key, self.api_endpoint)
		self.flags.credential_probe = result

		if result["ok"]:
			frappe.msgprint(
				_("Credentials verified with {0}.").format(self.provider),
				indicator="green",
				alert=True,
			)
			return
		if result["code"] in model_health.CREDENTIAL_PROBE_CODES:
			frappe.throw(
				_("{0} The model was not saved.").format(_capitalise(result["detail"])),
				title=_("Credential check failed"),
			)
		frappe.msgprint(
			_(
				"Could not verify the credentials right now: {0}. Saved anyway; the "
				"scheduled check will try again."
			).format(result["detail"]),
			indicator="orange",
			title=_("Credentials not verified"),
		)


def _capitalise(text: str) -> str:
	text = (text or "").strip()
	if not text:
		return text
	text = text[0].upper() + text[1:]
	return text if text.endswith((".", "!", "?")) else text + "."
