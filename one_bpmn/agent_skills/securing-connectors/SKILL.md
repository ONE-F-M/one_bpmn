---
name: "securing-connectors"
description: "The safety rules for a connector: where credentials live, which operations may be tested, what goes in a log, and the limits every operation needs. Use this skill when an operation handles authentication, when you are tempted to put a value in a draft, or when writing a Python handler. Do NOT use it for the shape of the manifest itself."
---

# A connector carries no secrets

You configure WHERE a credential is read from. A person supplies the value, in
the desk, after the connector is written.

- Never invent a secret, API key, token or password, and never put one in a
  draft, a template, a URL or a test call.
- If the API needs a value the work order does not give you, declare the field
  and say what is missing. A plausible looking placeholder is worse than a gap,
  because it looks configured.
- The connector is written disabled on purpose. Say in your summary that a person
  must paste the credential into Secret and tick Enabled.

## Calls that leave the bench

- Only ever test read only operations. Never one that creates, updates or deletes
  data in someone's real account.
- Every operation needs a timeout. An operation with none holds a worker until
  the provider decides to answer.
- A single response over 2 MB is refused. An operation that could return an
  unbounded amount needs a handler that pages and caps.

## Logs and reports

- Never put an authorization header, a token or a password into a log line, a
  comment or a report. Say "the Authorization header was sent" and nothing more.
- Quote the provider's error verbatim when a test fails, with any credential in
  it removed.

## Python handlers

A handler runs our code against someone else's service, so:

- Build the URL from the connector's configured base and the declared fields. Do
  not accept a full URL from the caller and fetch it.
- Read credentials from the context the executor passes in. Never from the
  environment and never from a literal.
- Handle the provider's errors. Returning a traceback to a process designer tells
  them nothing they can act on.
