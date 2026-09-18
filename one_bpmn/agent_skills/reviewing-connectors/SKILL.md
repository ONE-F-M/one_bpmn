---
name: "reviewing-connectors"
description: "What the connector review gate rejects, how to fix each issue, and the rule for proving an operation works before you finish. Use this skill when review_connector returns issues, or before calling write_connector or test_operation. Do NOT use it for deciding whether an operation needs a Python handler."
---

# Never write a draft that has not passed review clean

`review_connector` is deterministic. It catches the mistakes that otherwise only
surface on a live call.

## What it rejects, and the fix

| Issue | Fix |
|---|---|
| A template references a field that was never declared | Declare the field on the operation, or stop referencing it |
| `params.values` used as a value | `values` is a dict method. Rename the field |
| A relative URL with no base | Set the base URL on the connector, or make the operation URL absolute |
| A body that stops being JSON once the expressions are filled in | Quote the expression inside the JSON, or build the body from declared fields |
| A dropdown with no choices | Give the field its options, or make it a plain text field |

## The loop

1. `draft_connector`.
2. `review_connector`.
3. Issues? Fix them by calling `draft_connector` again with corrected
   instructions, then review again.
4. Clean? `write_connector`.

`write_connector` gates on the verdict recorded by the last review, with a
fingerprint of the draft it reviewed. A draft redrawn after a clean review is a
new draft and needs a new review. There is no way around this and no reason to
try.

## Proving it works

Prove the HTTP operations where you honestly can.

- No credential needed: call `test_operation` on ONE safe read only operation.
- Credential needed and you do not have it: say plainly that the test waits on
  the secret. Never guess a key.
- Never call an operation that creates, updates or deletes data in a real
  account.

An honest "not tested, and here is why" is worth more than a test you skipped
quietly.

## Finishing

Call `finalize` exactly once, last, even when the job could not be finished. Name
what is missing. The connector is written disabled, so the summary has to say
that a person must supply the credential and tick Enabled.
