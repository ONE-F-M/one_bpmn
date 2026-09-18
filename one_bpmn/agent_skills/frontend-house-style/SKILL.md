---
name: "frontend-house-style"
description: "How the front end of this bench is written: frappe-ui components, script setup, Tailwind tokens, frappeRequest for data, and the size limit on a component. Use this skill when writing or editing a .vue file in the Processa application or a desk .js file. Do NOT use it for the Ionic mobile app, which has its own conventions."
---

# House style

## Vue

- Build from frappe-ui components: `Button`, `FormControl` with `type="select"`,
  `Dialog`. A hand rolled control re-implements focus, keyboard handling and dark
  mode, and does it worse.
- `component_catalogue` lists the components the installed frappe-ui really has.
  Importing one that does not exist is the commonest way to break this build.
- Use `script setup`. Prefer `computed` over methods. Clean up listeners in
  `onBeforeUnmount`.
- Never put `v-if` and `v-for` on one element. Never write `v-for` without a key.
- Colours come from Tailwind tokens. No hex literals.
- Fetch data with `frappeRequest`. Do not introduce `fetch` or `axios`.

## Desk JavaScript

- `frappe.ui.form.on` for form scripts, and match the siblings already in that
  folder.
- No inline `style="..."` in HTML built by a script. Use Frappe and Bootstrap
  classes.
- Wrap user facing strings in `__()`.

## Size

Components here are already large. Leave a file the same size or smaller than you
found it. Past about three hundred lines of script, extract something instead of
adding to it.

## Before you edit

Read the file you are changing, plus one sibling that already does the same kind
of thing, so yours matches how they are written. For anything involving a form
field, call `doctype_fields`: it reads the live metadata including custom fields,
which the repository JSON does not show, and this bench has over a thousand.
