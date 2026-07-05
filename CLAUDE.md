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

Follow root [`CLAUDE.md`](../CLAUDE.md) for Frappe conventions.
