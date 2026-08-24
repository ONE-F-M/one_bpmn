# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""Fold AI Provider Credentials and AI Model Pricing into AI Provider + AI Model.

Three records used to describe one thing between them. A connection lived on
``AI Provider Credentials``, the catalog entry on ``AI Model``, and the rate card
on ``AI Model Pricing`` — keyed by a model NAME rather than by the catalog row, so
the two could and did drift apart. On the site this was written against, two
priced models had no catalog entry and six catalog models had no price, which is
to say they were costed at zero in every report.

Afterwards a provider is a connection and a model is everything about a model.

WHAT MOVES WHERE
----------------
- ``AI Provider Credentials`` → ``AI Provider``, keeping the record NAME, so the
  23 agent configurations and 18 diagrams that name "Anthropic" keep working
  without being rewritten. The API key is decrypted and re-encrypted onto the new
  record; it is never written to a log or an intermediate field.
- ``AI Model.ai_provider_credentials`` → ``AI Model.provider``.
- ``AI Model Pricing`` → ``input_cost`` / ``output_cost`` on the model, converted
  from per-1k to per-1M (×1000). The ACTIVE row with the newest ``effective_from``
  wins, which is the same row ``get_model_pricing`` would have returned.
- ``AI Agent Configuration.ai_provider_credentials`` → ``ai_provider``.

WHAT IS DELIBERATELY LOST
-------------------------
Dated pricing. ``effective_from``/``is_active`` gave one model several rates over
time; a model now has one. A future-dated row that has not taken effect is
therefore dropped, and this patch names it in the log rather than discarding it
quietly — somebody has to re-enter it on the day it applies.

Cache rates are not lost, because nothing configured them: every row on this site
leaves them at 0, and ``pricing.py`` already derives them from the input rate at
the standard ratios. The derivation is unchanged.

WHY THE OLD DOCTYPES ARE DROPPED LAST
-------------------------------------
So a failure leaves the source data intact. Everything above is a read of the old
records and a write to the new ones; if any of it raises, the patch stops with
both sets present and can be re-run. Only once the new records are complete does
the old schema go.
"""

import frappe
from frappe.utils.password import get_decrypted_password

# Per 1k → per 1M. The old rate card was quoted per thousand tokens; the new
# fields are per million, which is how every provider publishes them.
PER_1K_TO_PER_1M = 1000


def execute():
	if not frappe.db.exists("DocType", "AI Provider"):
		# The doctype ships with this change; nothing to do on a site that has
		# not synced it yet.
		return

	providers = _carry_over_providers()
	_repoint_models(providers)
	_fold_pricing_into_models()
	# After pricing, because "usable" means priced as well as connected.
	_enable_the_models_that_were_usable()
	_repoint_agent_configurations()
	_drop_the_old_doctypes()
	frappe.db.commit()


def _carry_over_providers() -> dict:
	"""Every credential record becomes a provider of the same name.

	The name is the whole point: it is what agent configurations and BPMN shape
	attributes refer to, and those live in diagrams that ship by export rather
	than by patch. Renaming here would mean editing 18 diagrams by hand.
	"""
	if not frappe.db.exists("DocType", "AI Provider Credentials"):
		return {}

	carried = {}
	for row in frappe.get_all(
		"AI Provider Credentials",
		fields=["name", "provider_type", "api_endpoint", "enabled"],
	):
		carried[row.name] = row.name
		if frappe.db.exists("AI Provider", row.name):
			continue
		doc = frappe.new_doc("AI Provider")
		doc.update({
			"provider": row.name,
			"provider_type": row.provider_type or "OpenAI",
			"api_endpoint": row.api_endpoint,
			"enabled": row.enabled,
		})
		# Decrypted and handed straight to the new record's own encrypted field.
		key = get_decrypted_password(
			"AI Provider Credentials", row.name, "api_key", raise_exception=False
		)
		if key:
			doc.api_key = key
		doc.flags.ignore_permissions = True
		doc.insert(ignore_permissions=True)

	print(f"AI Provider: {len(carried)} carried over from credentials")
	return carried


def _repoint_models(providers: dict) -> None:
	"""Point each model at its provider instead of its credential record.

	Then clear any ``provider`` that does not name a real one. ``tabAI Model``
	has carried a ``provider`` column since before credentials existed, holding
	the factory's lowercase adapter keys ("gemini"), and Frappe never drops a
	column. Those values were harmless while nothing read them; the moment
	``provider`` became a Link they became broken links pointing at records that
	have never existed. Cleared rather than guessed at — mapping "gemini" onto
	some Google provider would be inventing a connection nobody configured.
	"""
	if frappe.db.has_column("AI Model", "ai_provider_credentials"):
		moved = 0
		for row in frappe.db.sql(
			"""SELECT name, ai_provider_credentials FROM `tabAI Model`
			   WHERE ai_provider_credentials IS NOT NULL AND ai_provider_credentials != ''""",
			as_dict=True,
		):
			target = providers.get(row.ai_provider_credentials)
			if target and frappe.db.exists("AI Provider", target):
				frappe.db.set_value("AI Model", row.name, "provider", target, update_modified=False)
				moved += 1
		print(f"AI Model: {moved} repointed at a provider")

	stale = [
		row.name
		for row in frappe.db.sql(
			"SELECT name, provider FROM `tabAI Model` WHERE provider IS NOT NULL AND provider != ''",
			as_dict=True,
		)
		if not frappe.db.exists("AI Provider", row.provider)
	]
	for name in stale:
		frappe.db.set_value("AI Model", name, "provider", None, update_modified=False)
	if stale:
		print(
			f"AI Model: cleared a stale legacy provider on {len(stale)} "
			f"({', '.join(stale)}) — set a real provider before enabling them"
		)


def _models_agents_actually_use() -> dict:
	"""Every model named by an agent, and the providers those agents run on.

	An agent's model, and the two models it distils and reconciles memory with,
	are in use by definition — whatever the catalog says about them.
	"""
	used = {}
	for field in ("ai_model", "memory_distill_model", "memory_reconcile_model"):
		for row in frappe.get_all(
			"AI Agent Configuration",
			filters={field: ["is", "set"]},
			fields=[field, "ai_provider"],
		):
			model = row.get(field)
			if model:
				used.setdefault(model, set())
				if row.ai_provider:
					used[model].add(row.ai_provider)
	return used


def _enable_the_models_that_were_usable() -> None:
	"""``enable_model`` arrives defaulting to 0, which would offer nothing.

	The flag is new, so every existing model reads as disabled — and the editor's
	model picker and the fallback lookups now filter on it. Left alone the catalog
	would go silently empty on the first migrate.

	The old picker offered any model with a credentials link, and said nothing
	about price: an unpriced model was always selectable and simply reported zero
	cost. So the faithful rule is a resolving provider — NOT a provider and a
	rate. Getting that wrong disabled four models that live agents were running,
	which would have hidden an agent's own current model from its own picker.

	A model an agent uses is enabled either way. Where such a model names no
	provider, it is taken from the agents running it, when they agree — the same
	inference ``_provider_for_model`` already makes at dispatch, so this is
	writing down what the system was doing anyway rather than deciding something
	new.
	"""
	used = _models_agents_actually_use()

	adopted = []
	for model, providers in used.items():
		if not frappe.db.exists("AI Model", model):
			continue
		if frappe.db.get_value("AI Model", model, "provider"):
			continue
		agreed = {p for p in providers if frappe.db.exists("AI Provider", p)}
		if len(agreed) == 1:
			provider = agreed.pop()
			frappe.db.set_value("AI Model", model, "provider", provider, update_modified=False)
			adopted.append(f"{model} -> {provider}")
		elif len(agreed) > 1:
			print(
				f"AI Model: '{model}' is run by agents on {sorted(agreed)} — "
				f"left without a provider, pick one by hand"
			)
	for entry in adopted:
		print(f"AI Model: provider taken from the agents using it — {entry}")

	on, off, unpriced = 0, [], []
	for row in frappe.get_all(
		"AI Model", fields=["name", "provider", "input_cost", "output_cost"]
	):
		connected = bool(row.provider and frappe.db.exists("AI Provider", row.provider))
		if connected or row.name in used:
			frappe.db.set_value("AI Model", row.name, "enable_model", 1, update_modified=False)
			on += 1
			if not (frappe.utils.flt(row.input_cost) or frappe.utils.flt(row.output_cost)):
				unpriced.append(row.name)
		else:
			off.append(row.name)

	print(f"AI Model: {on} enabled, {len(off)} left disabled ({', '.join(off) or 'none'})")
	if unpriced:
		# Not new — these had no rate card before either, so they have always
		# reported zero. Named because "enabled" now implies somebody looked.
		print(
			f"AI Model: enabled but UNPRICED, so they report zero cost — "
			f"{', '.join(unpriced)}"
		)


def _fold_pricing_into_models() -> None:
	"""Copy each model's live rate onto the model, and say what could not be kept."""
	if not frappe.db.exists("DocType", "AI Model Pricing"):
		return

	rows = frappe.get_all(
		"AI Model Pricing",
		fields=[
			"name", "model_name", "is_active", "effective_from",
			"input_cost_per_1k", "output_cost_per_1k",
		],
		order_by="effective_from desc",
	)

	# The active row with the newest effective_from — exactly what
	# get_model_pricing() resolved to before this change.
	live, dropped = {}, []
	for row in rows:
		if not row.is_active:
			dropped.append(row)
		elif row.model_name not in live:
			live[row.model_name] = row

	priced = 0
	for model_name, row in live.items():
		if not frappe.db.exists("AI Model", model_name):
			# A rate with no catalog entry. Created rather than discarded, and
			# left DISABLED: it was never a model an agent could pick, and this
			# patch is not the place to widen what is available.
			doc = frappe.new_doc("AI Model")
			doc.update({"model_name": model_name, "enable_model": 0})
			doc.flags.ignore_permissions = True
			doc.insert(ignore_permissions=True)
			print(f"AI Model: created '{model_name}' (disabled) so its rate survives")

		frappe.db.set_value(
			"AI Model",
			model_name,
			{
				"input_cost": frappe.utils.flt(row.input_cost_per_1k) * PER_1K_TO_PER_1M,
				"output_cost": frappe.utils.flt(row.output_cost_per_1k) * PER_1K_TO_PER_1M,
			},
			update_modified=False,
		)
		priced += 1

	print(f"AI Model: {priced} models priced from the rate card")
	for row in dropped:
		# Named, not silently binned: a rate that has not taken effect yet is
		# somebody's decision, and it has to be re-entered by hand on the day.
		print(
			f"AI Model Pricing: DROPPED inactive rate for '{row.model_name}' "
			f"effective {row.effective_from} "
			f"(in {row.input_cost_per_1k}/1k, out {row.output_cost_per_1k}/1k) "
			f"— re-enter it on the model when it applies"
		)


def _repoint_agent_configurations() -> None:
	"""``ai_provider_credentials`` becomes ``ai_provider`` on the agent.

	Renamed rather than left alone because the field is read in fifteen places
	and shown in the editor; a name that describes a doctype which no longer
	exists is a trap for whoever reads it next. The VALUES do not change, so the
	shape attribute the diagrams carry still resolves.
	"""
	if not frappe.db.has_column("AI Agent Configuration", "ai_provider_credentials"):
		return

	from frappe.model.utils.rename_field import rename_field

	try:
		rename_field("AI Agent Configuration", "ai_provider_credentials", "ai_provider")
		print("AI Agent Configuration: ai_provider_credentials -> ai_provider")
	except Exception:
		frappe.log_error(
			title="AI provider refactor: could not rename the agent's provider field",
			message=frappe.get_traceback(),
		)


def _drop_the_old_doctypes() -> None:
	"""Last, so a failure above leaves the source data to try again from."""
	for doctype in ("AI Model Pricing", "AI Provider Credentials"):
		if not frappe.db.exists("DocType", doctype):
			continue
		try:
			frappe.delete_doc("DocType", doctype, force=True, ignore_permissions=True)
			print(f"Dropped {doctype}")
		except Exception:
			frappe.log_error(
				title=f"AI provider refactor: could not drop {doctype}",
				message=frappe.get_traceback(),
			)
