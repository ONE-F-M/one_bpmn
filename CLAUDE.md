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

## Adding a field to AI Agent Configuration

**A new field on `AI Agent Configuration` is not done until it is configurable
from Processa.** Desk is not the configuration surface — a process owner
configures their agent in the Processa editor, so a field they cannot reach
there does not exist as far as they are concerned. Adding the doctype field and
stopping is a half-delivered change.

Six places, all required:

1. `one_bpmn/one_bpmn/doctype/ai_agent_configuration/ai_agent_configuration.json`
   — the field, and its entry in `field_order`.
2. `one_bpmn/agents/agent_config_resolver.py` → `_CONFIG_TO_SHAPE` — config
   field to shape attribute (`aiYourField`), so the resolver hands it out.
3. …and `_SHAPE_TO_CONFIG` — the reverse, so the modal can write it back.
4. `spiff/src/components/AIAgentConfigModal.vue` — the default in the form
   object, the hydration entry, the key in `MEMORY_FORM_KEYS` (the overlay only
   fills keys already present on `form.value`), and the assignment in the save
   mapping. A checkbox also needs its key in `BOOLEAN_FORM_KEYS`, because the
   doctype stores 0/1 and the modal binds a boolean.
5. The template block itself, in the section it belongs to.
6. `yarn build` in `spiff/` — `bench build` does NOT compile the Vue app.

Miss any of 2–5 and the field silently does nothing: it saves in Desk, reads
back as blank in Processa, or is quietly overwritten on the next save from the
modal.

Follow root [`CLAUDE.md`](../CLAUDE.md) for Frappe conventions.
