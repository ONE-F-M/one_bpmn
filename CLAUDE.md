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

## Never commit a process map or its config bundle

A `.bpmn` file and its `*_config.json` are **not source**, and they do not belong
in this repo. A map moves between sites through Processa's own export/import,
which carries the diagram, its Server Scripts and its workflow states together and
compiles on arrival. The moment a copy is committed here, someone edits the map in
the modeler and the committed file is silently wrong, with nothing to reconcile the
two. `one_bpmn/exports/*.bpmn` and `*_config.json` are gitignored for this reason.

The same rule from the other direction: **never patch in a map or its Server
Scripts.** A patch may seed an `AI Agent Configuration` — that is a record, not a
diagram — and nothing else.

So a story that changes a map ships as: code and tests in the PR, the map by
export/import, and a line in the PR saying which maps to import and in what order.

Follow root [`CLAUDE.md`](../CLAUDE.md) for Frappe conventions.
