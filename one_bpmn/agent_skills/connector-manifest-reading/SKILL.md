---
name: "Connector Manifest Reading"
description: "How to read what read_api_docs returns, machine readable spec or prose page, and turn it into the operations a connector needs. Use this skill when a connector request names a reference or an OpenAPI document. Do NOT use it for questions about what a connector is."
---

# Read the API before you design anything

If the work order names a documentation page or an OpenAPI or Swagger URL, call
`read_api_docs` on it FIRST. Design from what the API actually offers, never from
what you remember about it.

## Two kinds of answer

**A machine readable spec** comes back as an endpoint catalogue with servers and
auth schemes. Build the manifest from it mechanically:

- The server entry is the connector's base URL.
- Each endpoint you were asked for becomes one operation.
- A path parameter becomes a required field, and the URL template references
  exactly that field.
- A query parameter the request needs becomes a field, required only if the API
  requires it.
- The auth scheme in the spec is the connector's auth type.

**A prose documentation page** comes back as readable text. There is no catalogue
to copy, so read it for the same five things: base URL, auth, the path of each
operation, the parameters it takes, and the shape of what it returns.

## Choose narrowly

Add only the operations the work order asks for. Every operation becomes a
dropdown entry that a process designer has to read and understand. A connector
with forty endpoints nobody asked for is harder to use than one with three.

## When the page does not answer

If the reference does not show what an operation returns, say so and design the
response mapping from the one field you are certain of. Do not invent a response
shape. A mapping built on a guess fails on the first real call, and the failure
looks like a broken connector instead of a missing fact.
