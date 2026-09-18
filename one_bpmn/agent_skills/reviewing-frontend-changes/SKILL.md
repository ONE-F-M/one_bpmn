---
name: "reviewing-frontend-changes"
description: "A fixed format for reporting problems found in front end code, with the checks that matter in this bench. Use this skill when asked to review a diff, a pull request or a file in the Processa application or desk JavaScript. Do NOT use it when you are the one making the change; verify your own work instead."
---

# Report one finding per line

```
[BLOCKER|MAJOR|MINOR] short title
File: path/to/file.vue:42
Issue: what is wrong, in one sentence.
Fix: what to do instead, in one sentence.
```

End with one line: `Approve`, `Approve with comments`, or `Changes requested`.

## Severity

- **BLOCKER**: it breaks the build, throws at run time, loses data, or exposes
  something it should not.
- **MAJOR**: wrong behaviour, a missing half (a script with no hook entry), an
  import of a component that does not exist.
- **MINOR**: style and consistency.

## What to check

- An imported frappe-ui component that the installed version really has.
- `v-for` without a key, `v-if` on the same element as `v-for`.
- Listeners added with no cleanup in `onBeforeUnmount`.
- `fetch` or `axios` in place of `frappeRequest`.
- Hex colours in place of Tailwind tokens.
- Inline `style="..."` in script built HTML.
- User facing strings not wrapped in `__()`.
- A desk script with no matching `hooks.py` entry.
- A field name guessed instead of read from live metadata.
- A file that grew past about three hundred lines of script.

## What not to do

Do not report formatting a linter already fixes. Do not rewrite the author's
approach when theirs works. Praise nothing; an empty finding list is the praise.
