# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""Give the models that have no rate one, so their traffic stops costing nothing.

Five enabled models carried no rate. That is not new — they had no rate-card row
before either — but it meant 4.36 million tokens, about a fifth of all traffic on
this site, were reported as free. Two of the five run Live chat agents, so the
under-reporting was continuous rather than historical.

Rates are the providers' published list prices per 1,000,000 tokens, confirmed
before being written.

ONLY FILLS WHAT IS EMPTY
------------------------
A model that already has a rate is left exactly as it is. A published price is a
starting point, not an authority — a site on negotiated or committed-use pricing
has the right number already, and a patch that overwrote it would silently
misreport spend in the opposite direction.

DOES NOT TOUCH HISTORY
----------------------
Cost is stamped on each AI Agent Run as it happens, so entering a rate now fixes
reporting from here on and leaves past runs at whatever they recorded. That is
deliberate: a run's cost is what it cost at the time, and rewriting it would make
the total depend on when you last edited the catalog.
"""

import frappe

# Published list price per 1M tokens, in USD.
RATES = {
	"claude-sonnet-4-5-20250929": (3.00, 15.00),
	"gpt-4o": (2.50, 10.00),
	"gpt-4.1": (2.00, 8.00),
	"gpt-4.1-mini": (0.40, 1.60),
	"o4-mini": (1.10, 4.40),
}

# Every rate here and every rate already on the site is a USD list price, and
# Insights formats costs as USD without converting. Stamping it makes that
# explicit instead of leaving it to a blank field — and corrects the rows that
# picked up the site's own default currency when they were created.
RATE_CURRENCY = "USD"


def execute():
	if not frappe.db.has_column("AI Model", "input_cost"):
		return

	priced, skipped = [], []
	for model, (input_cost, output_cost) in RATES.items():
		if not frappe.db.exists("AI Model", model):
			continue
		current = frappe.db.get_value(
			"AI Model", model, ["input_cost", "output_cost"], as_dict=True
		)
		if frappe.utils.flt(current.input_cost) or frappe.utils.flt(current.output_cost):
			skipped.append(model)
			continue
		frappe.db.set_value(
			"AI Model",
			model,
			{"input_cost": input_cost, "output_cost": output_cost},
			update_modified=False,
		)
		priced.append(f"{model} ({input_cost}/{output_cost} per 1M)")

	if frappe.db.has_column("AI Model", "currency") and frappe.db.exists("Currency", RATE_CURRENCY):
		frappe.db.sql(
			"""UPDATE `tabAI Model` SET currency = %s
			   WHERE (input_cost > 0 OR output_cost > 0)
			     AND (currency IS NULL OR currency != %s)""",
			(RATE_CURRENCY, RATE_CURRENCY),
		)

	frappe.db.commit()
	for entry in priced:
		print(f"AI Model: priced {entry}")
	if skipped:
		print(f"AI Model: left alone, already priced — {', '.join(skipped)}")
