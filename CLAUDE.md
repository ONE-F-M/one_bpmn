# one_bpmn

BPMN editor integration for Frappe, powered by [bpmn-js](https://bpmn.io/toolkit/bpmn-js/) and [SpiffWorkflow](https://www.spiffworkflow.org/). Accessible at `/spiff`.

## Stack

- Frappe v15 backend (Python)
- Vue.js frontend (bpmn-js + SpiffWorkflow properties panel)
- Node.js 20.x, Yarn

## Features

- Multiple diagrams per process
- Tabbed editing interface
- Formatting toolbar + custom shape library
- SpiffWorkflow properties panel integration

## Key Paths

- `one_bpmn/` — Python app (controllers, hooks, API)
- `spiff/` — Vue.js frontend source

## Commands

```bash
yarn build        # Build Vue frontend
bench migrate     # Apply schema changes
bench restart     # Restart after Python changes
```

## Working on an AI agent story

Two things decide the whole shape of an agent, so settle them **before** designing
or researching anything:

1. **Which kind of agent is it?** `agent_type` is `Chat` or `Background`, and they
   share almost nothing. A Chat agent needs a `chat_mode_label`, a conversation
   loop in its map, and it faces the adversarial go-live gate. A Background agent
   has none of those: it is started by a record insert (an `A2A Task` for a
   delegated worker), reads its brief off that record, and writes its answer back
   onto it. Building the wrong one is a rebuild, not an edit.
2. **How is it invoked?** A chat surface, an orchestrator delegating over A2A, a
   record trigger, or a step inside a larger process. This determines the start
   event, and therefore the map.

Ask for both if a story does not say. Everything else — prompts, tools, model —
is cheap to change afterwards; these two are not.

**Read the live examples before inventing a pattern.** Staging (the BA site — see
`Processa Settings` → BA Sync block, read-only) carries working agents for most
shapes: a delegating orchestrator and four delegated specialists for A2A, plus the
chat agents. Copying a map that already runs beats deriving one from the code, and
the layout conventions (lane at y=180, 100x80 tasks 130 apart, 50x50 gateways,
ad-hoc Tools sub-process 550x240 under the agent task) come from those maps too.

When copying a map, **fix `process_name` before touching `is_active`** — a copy
inherits its source's `Process`, and activating it silently deactivates the map it
was cloned from.

Follow root [`CLAUDE.md`](../CLAUDE.md) for Frappe conventions.

## Writing an eval case

A case has three pieces of text and they do three different jobs. Keep them apart.

- **The case title** names the behaviour being tested, route and all: "A server-side rule change goes to the Dev Agent". Only a person reading the suite sees it.
- **The fixture** — the work item, the A2A task, whatever record the case runs against — is written the way its reporter would have written it. Never title it after the answer. On the map path the record IS the prompt: the first step of the map builds the brief from the title and the description, so a work item titled "A server-side rule change" hands the model the answer before it reaches the brief the decision is supposed to come from.
- **The case's prompt field** carries a full sentence or two summarising the brief, not a label. On the map path it is never sent to the model; it is snapshotted onto the result row and is the only line a reader sees beside the verdict, so "A server-side rule change" tells them nothing. It IS the message for a chat agent's case and for a direct model call, where the same fullness applies.

Two rules that follow: nothing in the case may name the expected answer where the agent can read it, and a case is only honest if the fixture alone contains every fact the agent needs to decide.

## House style

Every checkable rule lives in `frappe-bench/.claude/rules/` and loads automatically: `house-style.md` always, `python-frappe.md` for Python, `vue-js.md` for JavaScript and Vue. The numbered set with ids A1 to F8 is `frappe-bench/.claude/rules/RULES.md`; cite an id when a PR body justifies an exception. Before you say a task is done, re-read your diff against `house-style.md`.
