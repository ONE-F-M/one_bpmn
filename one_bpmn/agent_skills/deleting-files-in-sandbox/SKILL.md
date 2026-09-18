---
name: "deleting-files-in-sandbox"
description: "What to do when a work order asks for a file to be removed, given that the sandbox has no delete tool and an emptied file breaks the app. Use this skill when the work order says delete, remove or retire a file, or when you are about to write an empty file. Do NOT use it for removing code from inside a file that stays."
---

# There is no delete tool

`write_file` writes content. Writing an empty string leaves a file that still
exists and is still loaded. For JSON and fixture files this is worse than doing
nothing: an empty `.json` fails `bench migrate` for every later run on the same
bench, so the next agent cannot work at all.

## What to do instead

1. Leave the file exactly as it is.
2. Make the change that stops the file being used: remove the hooks.py entry, the
   import, the patches.txt line, the route, whichever applies. A file nothing
   loads is already retired in every way that matters at run time.
3. Name the file in your pull request summary under a heading a person can act
   on:

```
To delete by hand:
  onefm_mcp/onefm_mcp/page/lumina/lumina.json
  onefm_mcp/onefm_mcp/page/lumina/lumina.js
Reason: the page record is removed by a patch and nothing loads these.
```

4. If removing a record as well as files, write a patch that deletes the record.
   A patch is code you can write; deleting the file is the part you cannot.

## Never

- Never write an empty file to stand in for a delete.
- Never write a file whose only content is a comment saying it is deleted.
- Never claim in your report that a file was deleted. Say it is listed for
  deletion.
