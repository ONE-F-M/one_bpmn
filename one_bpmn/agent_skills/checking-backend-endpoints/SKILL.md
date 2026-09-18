---
name: "checking-backend-endpoints"
description: "A mobile feature is usually half in the mobile app and half in the backend, so how to check an endpoint exists before building a screen that calls it. Use this skill when the work order needs data the app does not have yet, or names an endpoint. Do NOT use it when the change is purely visual."
---

# You can only do the mobile half

A feature here is normally two changes in two repositories: an endpoint in the
`one_fm` app, and screens in the mobile app. You change the mobile app only.

## Check first, build second

1. Call `list_backend_endpoints` and find the endpoint the screen needs.
2. If it exists, note its exact name in the form `v1.<module>.<function>` and use
   it through `httpService`.
3. If it does not exist, stop. Say which endpoint is missing, what it would have
   to return, and that the backend work has to happen first. That is a complete,
   useful answer, and it is better than a screen that calls a name nobody wrote.

## Never

- Never invent an endpoint name and build against it.
- Never write a host or full URL into the code. The host comes from the
  environment.
- Never reach the backend with `fetch` or `axios`. Every request goes through
  `httpService` from `src/api/http.service.ts`.

## Note in your report

Say which endpoints the change calls and whether you confirmed each one exists.
A reviewer cannot tell a confirmed endpoint from a guessed one by reading the
diff.
