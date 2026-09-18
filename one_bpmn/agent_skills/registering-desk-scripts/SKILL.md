---
name: "registering-desk-scripts"
description: "Desk JavaScript is two halves, the script file and the hooks.py entry that loads it, and a pull request with only one half changes nothing. Use this skill when adding or moving a desk form, list, tree or page script. Do NOT use it for Vue files in the Processa application, which are bundled by Vite."
---

# A script nobody registers never runs

Frappe loads a desk script because `hooks.py` names it. Write the file and stop,
and the behaviour is missing with no error anywhere.

## Both halves, one run

1. Write or edit the `.js` file.
2. Call `hook_entry` with the app, the hook, the DocType and the file path. It
   returns the exact line `hooks.py` needs and where it goes, and it refuses an
   app that is not ours.
3. `edit_file` that line into `hooks.py` in the same run.

## Which hook

| What you wrote | Hook |
|---|---|
| Form script for one DocType | `doctype_js` |
| List view script | `doctype_list_js` |
| Tree view script | `doctype_tree_js` |
| Calendar view script | `doctype_calendar_js` |
| Desk page | `page_js` |
| Loaded on every desk page | `app_include_js` |
| Loaded on website pages | `web_include_js` |

## Check before you finish

- The path in `hooks.py` matches where the file actually is.
- An existing entry for that DocType was extended, not replaced. Two apps can
  both script one DocType, and so can two files in one app.
- `bench build` is a person's job after merge. Say so in the summary when the
  change needs it.
