---
name: "customising-upstream-doctypes"
description: "Which app a change belongs in, and how to customise a DocType that another app owns without editing that app. Use this skill when the screen or DocType you were sent to might live in frappe, erpnext, hrms, helpdesk, payments, lending or wiki, before you edit any file. Do NOT use it when the target is already one of our own apps."
---

# Decide the app before you write anything

**Ours:** `one_fm`, `one_bpmn`, `onefm_mcp`, `frappe_agile`, `onefm_sso`. Change
the file that already renders the screen.

**Not ours:** `frappe`, `erpnext`, `hrms`, `helpdesk`, `payments`, `lending`,
`wiki`. Never target these. Work there sits in someone else's review queue and
the next upgrade wipes it.

## The route for a DocType we do not own

Write the behaviour in `one_fm` and register it against that DocType there.

| What you need | Where it goes |
|---|---|
| Form behaviour | A `.js` file in `one_fm`, registered with `doctype_js` in its `hooks.py` |
| Server side logic | A function in `one_fm`, registered with `doc_events` in its `hooks.py` |
| A new field | `create_custom_fields` in a `one_fm` patch |
| A changed field property | `make_property_setter` in a `one_fm` patch |

`one_fm` already customises about fifty ERPNext and HRMS DocTypes this way, so
there is a sibling to copy for whatever you are adding.

## Find out who owns it first

Call `locate_ui` with the DocType or route. It reads this bench as deployed:
which app owns the screen, which hooks register it, which Client Script rows and
Property Setters shape it. If it says the target does not exist, say so and stop.
Do not invent a plausible file.
