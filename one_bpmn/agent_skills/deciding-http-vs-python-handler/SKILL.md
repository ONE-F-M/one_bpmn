---
name: "deciding-http-vs-python-handler"
description: "The two questions that decide whether a connector operation can be declarative configuration or genuinely needs a Python handler, with the list of reasons an operation fails them. Use this skill when designing an operation, or before calling propose_python_handler. Do NOT use it for choosing a base URL or an auth type."
---

# One request, one body

An HTTP operation is ONE request, and everything it returns has to be in that
request's body. That is not a preference. It is what the executor does: it fills
in your templates, makes a single call, and hands back the parsed body. It never
loops, it keeps nothing between calls, and it throws the response HEADERS away.
Only the body reaches your response mapping.

## Ask two questions about every operation

1. Can you name the one request that answers it?
2. Is everything you need inside that one response body?

Two yeses and it is an HTTP operation. Any no and it is a Python handler.

## The usual reasons for a no

- The answer spans several pages and you have to follow a next page link.
- The next page is named in a response HEADER. The header is gone before your
  mapping runs, so no template can reach it.
- You need any other response header: a rate limit budget, an ETag, a Location.
- The request has to be signed or computed before it is sent.
- Several calls have to happen in order, or one call's output feeds the next.
- Results have to be gathered up, counted, de-duplicated or capped.
- The response needs more reshaping than picking values out by dotted path.

## A worked example

"Fetch a repository" is one GET and the whole answer is in the body. That is an
HTTP operation.

"List every open issue" comes back thirty at a time, names the next page in a
response header, needs the pages joined into one list, and needs a cap so a huge
repository cannot run forever. Three separate reasons it cannot be configuration.

Two operations against the same API, and they do not get the same answer. Decide
operation by operation, never once for the whole connector.

## One more limit

A single response over 2 MB is refused outright. An operation that could return
an unbounded amount of data needs a handler that pages and caps, whatever the
next page is called.

## If it is a handler

Write the complete function taking `(params, ctx)` and returning a dict. Say in
one sentence which of the two questions it failed, and put that sentence in the
pull request. A handler is delivered as a pull request, so the connector stays
disabled until a person merges and deploys it. Do not call `test_operation` on an
operation whose handler you just proposed: the code is not there yet, and the
failure would mean nothing.

Prefer configuration every time it will do the job. Configuration can be read and
changed by someone who is not a developer. Code cannot.
