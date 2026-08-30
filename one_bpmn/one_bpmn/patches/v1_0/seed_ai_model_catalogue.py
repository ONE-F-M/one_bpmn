# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""Give every site the same AI catalogue: the providers, the models, the facts.

The three sites had drifted badly. One had two providers and eighteen models;
another had three providers, one of which routes nowhere, and three models with
no provider at all; the third had a single credential, six orphaned models and
NO pricing whatsoever, which means every agent run there was reported as free.

This lands the same catalogue everywhere, and it is written to be run on a site
that is already wrong rather than a clean one.

NO API KEYS
-----------
Deliberately. A key is per-site, it is a secret, and a patch is source code that
lands in a git history and a build artifact. Every model this creates is left
DISABLED for that reason — the doctype makes the key mandatory once a model is
enabled, so an operator entering the key is what switches a model on, and that
is the correct order. Existing rows keep whatever enable_model they already had.

ONLY FILLS WHAT IS EMPTY — EXCEPT A RATE THAT IS KNOWN TO BE SUPERSEDED
-----------------------------------------------------------------------
A rate, an endpoint or a context window already on the site is left exactly as
it is. Published list prices are a starting point, not an authority: a site on
negotiated pricing already holds the right number, and overwriting it would
misreport spend in the other direction.

Scheduled rate changes are the one exception, and they need one. The old rate
card carried effective_from, so a price rise could be entered in advance and
would take effect on its date. Folding pricing onto AI Model dropped that: there
is one rate per model and no date, so a change now needs a human to remember it.
claude-sonnet-5 is the live example — introductory $2/$10 through 2026-08-31,
$3/$15 from 2026-09-01 — and forgetting it under-reports that model by a third.

SCHEDULED_RATES restores the mechanism narrowly. A change applies only once its
date has passed AND the stored rate still matches the exact published rate it
supersedes, so a negotiated or hand-edited rate is never touched — it will not
match. Because a patch runs once and these have dates in the future,
apply_due_rates() also runs nightly from the scheduler.

WHAT IT INFERS, AND WHAT IT WILL NOT
------------------------------------
A model with no provider gets one derived from its id — gpt-*/o*-* is OpenAI,
claude-* is Anthropic, gemini-* is Google. That is safe because the id prefix is
the vendor's own naming, and it is the only way to rescue the orphaned rows.

Context windows and output caps are filled for the Claude models only. Those
came from the Anthropic Models API and are exact. The equivalent numbers for the
OpenAI and Gemini rows are deliberately left blank rather than guessed: they feed
budgeting and truncation, and a plausible wrong number there is worse than an
empty field, which at least reads as unknown.
"""

import frappe

# The provider record's NAME is its dialect, so these are the only names that
# route. "Gemini" resolves too and is left alone where a site already uses it.
PROVIDERS = ("Anthropic", "OpenAI", "Google")

# Model id prefix -> the provider it belongs to, for rescuing orphaned rows.
BY_PREFIX = (
	("claude-", "Anthropic"),
	("gpt-", "OpenAI"),
	("o1-", "OpenAI"),
	("o3-", "OpenAI"),
	("o4-", "OpenAI"),
	("gemini-", "Google"),
)

# provider, input $/1M, output $/1M, context window, max output tokens.
# Claude context/output figures are from the Anthropic Models API. The OpenAI
# and Gemini rows carry rates only — see the module docstring.
CATALOGUE = {
	"claude-opus-5":              ("Anthropic",  5.00, 25.00, 1000000, 128000),
	"claude-sonnet-5":            ("Anthropic",  2.00, 10.00, 1000000, 128000),
	"claude-fable-5":             ("Anthropic", 10.00, 50.00, 1000000, 128000),
	"claude-opus-4-8":            ("Anthropic",  5.00, 25.00, 1000000, 128000),
	"claude-sonnet-4-6":          ("Anthropic",  3.00, 15.00, 1000000, 128000),
	"claude-sonnet-4-5-20250929": ("Anthropic",  3.00, 15.00, 1000000,  64000),
	"claude-haiku-4-5":           ("Anthropic",  1.00,  5.00,  200000,  64000),
	"claude-haiku-4-5-20251001":  ("Anthropic",  1.00,  5.00,  200000,  64000),
	"gpt-4o":                     ("OpenAI",     2.50, 10.00, None, None),
	"gpt-4o-mini":                ("OpenAI",     0.15,  0.60, None, None),
	"gpt-4.1":                    ("OpenAI",     2.00,  8.00, None, None),
	"gpt-4.1-mini":               ("OpenAI",     0.40,  1.60, None, None),
	"gpt-4.1-nano":               ("OpenAI",     0.10,  0.40, None, None),
	"gpt-5-nano":                 ("OpenAI",     0.05,  0.40, None, None),
	"o4-mini":                    ("OpenAI",     1.10,  4.40, None, None),
	"gemini-2.0-flash":           ("Google",     0.10,  0.40, None, None),
	"gemini-2.0-flash-lite":      ("Google",     0.075, 0.30, None, None),
	"gemini-2.5-flash-lite":      ("Google",     0.10,  0.40, None, None),
}

# Every model here is a chat model that takes tools and structured output. Vision
# is the one that genuinely varies, so it is listed rather than assumed.
NO_VISION = ("gpt-5-nano", "o4-mini")

RATE_CURRENCY = "USD"

# Rates that change on a date. (model, from, new in, new out, the published rate
# it replaces). Applied only on or after the date, and only to a site still
# holding the exact rate being superseded.
SCHEDULED_RATES = (
	# Sonnet 5's introductory pricing ends 2026-08-31.
	("claude-sonnet-5", "2026-09-01", 3.00, 15.00, 2.00, 10.00),
)


def apply_due_rates() -> list:
	"""Apply any scheduled rate whose date has passed. Safe to run repeatedly.

	Also wired to the nightly scheduler, because a patch runs once and these
	dates are in the future when the patch lands.
	"""
	from frappe.utils import flt, getdate, nowdate

	applied = []
	for model, start, new_in, new_out, old_in, old_out in SCHEDULED_RATES:
		if getdate(nowdate()) < getdate(start):
			continue
		if not frappe.db.exists("AI Model", model):
			continue
		row = frappe.db.get_value("AI Model", model, ["input_cost", "output_cost"], as_dict=True)
		# Only a site still on the exact superseded published rate. Anything else
		# is somebody's own number and is not ours to overwrite.
		if flt(row.input_cost) != old_in or flt(row.output_cost) != old_out:
			continue
		frappe.db.set_value("AI Model", model, {"input_cost": new_in, "output_cost": new_out},
		                    update_modified=False)
		frappe.db.commit()
		applied.append(f"{model} {old_in}/{old_out} -> {new_in}/{new_out} (due {start})")
	return applied


def _provider_for(model_id: str) -> str | None:
	for prefix, provider in BY_PREFIX:
		if model_id.startswith(prefix):
			return provider
	return None


def _ensure_providers(needed):
	for name in needed:
		if not frappe.db.exists("AI Provider", name):
			frappe.get_doc({"doctype": "AI Provider", "provider": name}).insert(
				ignore_permissions=True
			)
			print(f"AI Provider: created {name}")


def _fill_only_empty(model: str, values: dict) -> list:
	"""Set the fields that are currently empty. Returns what it changed."""
	current = frappe.db.get_value("AI Model", model, list(values), as_dict=True)
	changed = {k: v for k, v in values.items() if v is not None and not current.get(k)}
	if changed:
		frappe.db.set_value("AI Model", model, changed, update_modified=False)
	return sorted(changed)


def execute():
	if not frappe.db.exists("DocType", "AI Provider") or not frappe.db.exists("DocType", "AI Model"):
		return
	# The one-field AI Provider and the model-held connection have to be in place
	# already; both arrive from patches that run before this one.
	if not frappe.db.has_column("AI Model", "api_key"):
		return

	_ensure_providers(PROVIDERS)

	created, updated = [], []
	for model, (provider, input_cost, output_cost, context, max_out) in CATALOGUE.items():
		if not frappe.db.exists("AI Model", model):
			# Disabled on purpose: the key is what enables it, and this patch
			# does not carry keys.
			frappe.get_doc({
				"doctype": "AI Model",
				"model_name": model,
				"provider": provider,
				"enable_model": 0,
			}).insert(ignore_permissions=True)
			created.append(model)

		fields = _fill_only_empty(model, {
			"provider": provider,
			"model_api_name": model,
			"input_cost": input_cost,
			"output_cost": output_cost,
			"currency": RATE_CURRENCY,
			"context_window": context,
			"max_output_tokens": max_out,
			"support_chat": 1,
			"support_tool_calling": 1,
			"support_structured_output": 1,
			"support_vision": 0 if model in NO_VISION else 1,
		})
		if fields and model not in created:
			updated.append(f"{model} ({', '.join(fields)})")

	# Anything already on the site that this catalogue does not name, but whose
	# id still says who made it. Production's six models were all in this state.
	rescued = []
	for row in frappe.get_all("AI Model", filters={"provider": ["in", ["", None]]},
	                          fields=["name"]):
		provider = _provider_for(row.name)
		if not provider:
			continue
		_ensure_providers([provider])
		frappe.db.set_value("AI Model", row.name, "provider", provider, update_modified=False)
		rescued.append(f"{row.name} -> {provider}")

	frappe.db.commit()
	for m in created:
		print(f"AI Model: created {m} (disabled — enter its API key to enable)")
	for m in updated:
		print(f"AI Model: filled {m}")
	for m in rescued:
		print(f"AI Model: gave an orphan its provider, {m}")

	for line in apply_due_rates():
		print(f"AI Model: scheduled rate applied, {line}")

	orphans = frappe.get_all("AI Model", filters={"provider": ["in", ["", None]]}, pluck="name")
	if orphans:
		print(f"AI Model: still without a provider, name says nothing — {', '.join(orphans)}")
