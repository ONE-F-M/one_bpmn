![Coverage](https://img.shields.io/badge/coverage-30%25%2B-brightgreen)

# ONE BPMN

A BPMN editor integration with Frappe Framework, powered by [bpmn-js](https://bpmn.io/toolkit/bpmn-js/) and [SpiffWorkflow](https://www.spiffworkflow.org/) extensions. The app provides a Vue.js-based BPMN process modeler accessible at `/spiff`, with support for multiple diagrams per process, a tabbed editing interface, a formatting toolbar, and SpiffWorkflow properties panel integration.

## Installation

### Prerequisites

- Frappe Bench setup
- Node.js 20.x
- Yarn package manager

### Install the App

```bash
# Get the app
bench get-app one_bpmn <repository-url>

# Install on your site
bench --site your-site.local install-app one_bpmn

# Run database migrations
bench --site your-site.local migrate
```

### Build Frontend Assets

```bash
# Navigate to the Vue.js frontend directory
cd apps/one_bpmn/spiff

# Install dependencies
yarn install

# Build for production
yarn build

# Copy assets to sites/assets
cd ../../../
bench build --app one_bpmn

# Clear cache
bench --site your-site.local clear-cache
```

### Development Mode

```bash
cd apps/one_bpmn/spiff
yarn dev --host
```

Access at `http://localhost:8080/spiff` (dev server).

---

## Project Structure

```
one_bpmn/
├── one_bpmn/                         # Frappe app module
│   ├── api/                          # Backend API submodules
│   │   ├── __init__.py               # Package docstring with module index
│   │   ├── process_map_api.py        # CRUD for Process Models and Process records
│   │   ├── compilation.py            # Compile, deploy, disable process models
│   │   ├── workflow_state.py         # Apply workflow states (BPMN service tasks)
│   │   ├── instance_api.py           # Process instance lifecycle
│   │   ├── editability.py            # Cross-site editability checks
│   │   ├── server_script_api.py      # Server script CRUD and AI integration
│   │   ├── canvas_comments.py        # Canvas comments and element assets
│   │   ├── notification_api.py       # In-app notification creation
│   │   ├── version_history.py        # Diagram XML version history
│   │   ├── script_version_history.py # Server script version history
│   │   └── utils.py                  # Shared helpers (role checks, field lookups)
│   ├── hooks.py                      # Frappe hooks configuration
│   ├── tasks.py                      # Scheduled/background task helpers
│   ├── one_bpmn/                     # DocTypes module
│   │   └── doctype/
│   │       └── bpmn_process_model/   # BPMN Process Model DocType
│   ├── public/
│   │   └── spiff/                    # Built Vue.js assets (generated)
│   │       ├── assets/               # JS, CSS, fonts
│   │       └── index.html
│   └── www/
│       └── spiff/                    # Frappe www route
│           ├── index.html            # HTML template (Jinja)
│           └── index.py              # Context provider
│
└── spiff/                            # Vue.js frontend source
    ├── package.json
    ├── vite.config.js
    ├── tailwind.config.cjs
    ├── postcss.config.cjs
    ├── index.html                    # Dev entry point
    └── src/
        ├── main.js                   # App entry point
        ├── main.css                  # Global styles (Tailwind)
        ├── App.vue                   # Root component
        ├── dayjs.js                  # DayJS configuration
        ├── router/
        │   └── index.js              # Vue Router configuration
        ├── views/
        │   ├── Home.vue              # Process list (table layout)
        │   └── Editor.vue            # BPMN editor with tabbed interface
        ├── components/
        │   ├── BpmnEditor.vue        # bpmn-js modeler wrapper with SpiffWorkflow extensions
        │   ├── EditorTabs.vue        # Bottom tab bar for open diagrams
        │   ├── EditorSidebar.vue     # Left sidebar for diagram list
        │   └── FormattingToolbar.vue  # Font, size, color, and alignment controls
        ├── renderers/
        │   ├── CustomTextStyleRenderer.js # Renders custom text styles (font, color, size)
        │   └── index.js              # Text style module registration
        ├── rules/
        │   ├── CustomRules.js         # Custom modeling rules for shape connections
        │   └── index.js              # Rules module registration
        ├── moddle/
        │   └── customTextStyleModdle.js # Moddle extension for text style XML attributes
        ├── i18n/
        │   ├── customTranslate.js    # Translation strings
        │   └── index.js              # Translation module registration
        └── utils/
            └── textStyleUtils.js     # Text style calculation utilities
```

---

## Backend API Endpoints

Organized into submodules under `one_bpmn/api/`:

### Process Model CRUD (`process_map_api`)

| Method | Endpoint | Description |
| ------ | -------- | ----------- |
| POST | `one_bpmn.api.process_map_api.save_process_model` | Save or update a BPMN diagram |
| POST | `one_bpmn.api.process_map_api.import_bpmn` | Import a .bpmn file (upsert by process_id) |
| GET | `one_bpmn.api.process_map_api.get_process_model` | Get a diagram by name |
| GET | `one_bpmn.api.process_map_api.list_process_models` | List all diagrams |
| GET | `one_bpmn.api.process_map_api.list_processes` | List Process records with diagram counts |
| GET | `one_bpmn.api.process_map_api.get_process_diagrams` | Get all diagrams for a process |
| GET | `one_bpmn.api.process_map_api.resolve_process_model_by_id` | Resolve process_id to model |
| GET | `one_bpmn.api.process_map_api.validate_bpmn_readiness` | Check deploy prerequisites |
| POST | `one_bpmn.api.process_map_api.rename_process_model` | Rename a diagram (fast path) |
| DELETE | `one_bpmn.api.process_map_api.delete_diagram` | Delete a diagram |

### Compilation & Deployment (`compilation`)

| Method | Endpoint | Description |
| ------ | -------- | ----------- |
| POST | `one_bpmn.api.compilation.compile_process_model` | Compile and deploy a process model |
| POST | `one_bpmn.api.compilation.disable_process_model` | Disable a deployed model |

All endpoints require authentication and use `@frappe.whitelist()` decorator.

---

## DocTypes

### BPMN Process Model

Stores BPMN process definitions with SpiffWorkflow engine data. Named by `title` field.

| Field              | Type                      | Description                                            |
| ------------------ | ------------------------- | ------------------------------------------------------ |
| `title`            | Data (unique, required)   | Diagram title (used as document name)                  |
| `process_name`     | Link → Process            | Parent process record                                  |
| `process_id`       | Data (unique, required)   | BPMN process ID extracted from XML (e.g., `Process_1`) |
| `category`         | Data                      | Optional category for grouping                         |
| `is_active`        | Check (default: 1)        | Whether the diagram is active                          |
| `description`      | Small Text                | Optional description                                   |
| `bpmn_xml`         | Code (XML)                | BPMN XML content                                       |
| `dmn_xml`          | Code (XML)                | DMN decision table XML                                 |
| `serialized_spec`  | JSON                      | SpiffWorkflow serialized process spec                  |
| `subprocess_specs` | JSON                      | SpiffWorkflow subprocess specifications                |
| `version`          | Int (default: 1)          | Auto-incrementing version number                       |
| `amended_from`     | Link → BPMN Process Model | Reference to previous version                          |

**Controller logic** (`bpmn_process_model.py`):

- `validate()` — validates `process_id` format (alphanumeric, underscores, hyphens, dots) and auto-extracts it from BPMN XML if not set
- `before_save()` — auto-increments `version` on each update

**Permissions**: System Manager (full), BPMN Admin (full), All (read-only).



## Frontend Routes

| Route                                      | View       | Description                                 |
| ------------------------------------------ | ---------- | ------------------------------------------- |
| `/spiff`                                   | Home.vue   | List of Process records with diagram counts |
| `/spiff/process/:process`                  | Editor.vue | Editor for a process (shows all diagrams)   |
| `/spiff/process/:process/diagram/:diagram` | Editor.vue | Editor with specific diagram active         |

---

## Features

### Home Page (`/spiff`)

- Table listing Process records with per-process diagram counts
- Columns: Title, Process Owner, Business Analyst, Status, Last Modified, Created
- Status derived from the most recent diagram's `is_active` flag
- Click a row to open the process editor

### Editor Page (`/spiff/process/:process`)

- Full-featured BPMN modeler powered by bpmn-js v17
- **Tabbed interface** at bottom for switching between diagrams
- **Left sidebar** for diagram list within the process
- **Properties panel** (toggleable) with BPMN and SpiffWorkflow properties
- **Formatting toolbar** with:
  - Font family and size selection
  - Bold, italic, underline text styling
  - Text and fill color pickers
  - Stroke color picker
  - Text alignment (left, center, right)
- Toolbar with Undo/Redo/Delete buttons
- Keyboard shortcuts:
  - `Ctrl+Z` — Undo
  - `Ctrl+Y` / `Ctrl+Shift+Z` — Redo
  - `Del` / `Backspace` — Delete selected elements
- Zoom controls: zoom in/out, reset, fit-to-screen
- Save persists to Frappe database
- HTML entity decoding for stored XML

### SpiffWorkflow Integration

- SpiffWorkflow properties panel extensions via forked [`bpmn-js-spiffworkflow`](https://github.com/ks093/bpmn-js-spiffworkflow)
- **Script editor** launch for Script Tasks, Pre/Post scripts
- **Markdown editor** launch for User Task / Manual Task instructions
- **Call Activity editor** launch for Call Activity elements
- Event bus handlers for SpiffWorkflow data requests (service tasks, JSON schemas, DMN files, data stores, messages)
- Loop data reference fix for multi-instance activities

### Custom Text Styling

- Per-element text formatting (font family, size, weight, style, decoration, alignment)
- Custom moddle extension persists styles as XML attributes (`custom:fontFamily`, `custom:fontSize`, etc.)
- Custom renderer applies styles during diagram rendering

### i18n / Translation

- Custom translate module for localizing BPMN palette, context pad, and properties panel labels

### Create Diagram Dialog

- Creates new diagram as a blank canvas (no pre-placed elements)
- Process is set to `isExecutable="false"` by default
- Links diagram to parent Process via `process_name`

---

## Key Dependencies

| Package                     | Version  | Purpose                                            |
| --------------------------- | -------- | -------------------------------------------------- |
| `bpmn-js`                   | ^17.11.1 | BPMN modeler core                                  |
| `bpmn-js-properties-panel`  | ^5.48.0  | Properties panel for BPMN elements                 |
| `bpmn-js-spiffworkflow`     | forked   | SpiffWorkflow extensions (ESM build)               |
| `@bpmn-io/properties-panel` | ^3.36.0  | Base properties panel framework                    |
| `frappe-ui`                 | 0.1.192  | Frappe UI components (Tooltip, TextEditor, Dialog) |
| `vue`                       | ^3.5.13  | Vue.js framework                                   |
| `vue-router`                | ^4.5.0   | Client-side routing                                |
| `dayjs`                     | ^1.11.7  | Date/time formatting                               |
| `@iconify/vue`              | ^5.0.0   | Icon component (Lucide icons)                      |
| `diagram-js-minimap`        | ^5.2.0   | Minimap module (currently disabled)                |
| `bpmn-js-color-picker`      | ^0.7.2   | Color picker integration                           |
| `tailwindcss`               | ^3.4.17  | Utility-first CSS (dev)                            |

---

## Development

### After Making Changes

```bash
cd apps/one_bpmn/spiff
yarn build
cd ../../../
bench build --app one_bpmn
bench --site your-site.local clear-cache
```

### Adding New Features

- **API endpoint**: Add to the appropriate submodule in `one_bpmn/api/` with `@frappe.whitelist()` (e.g. process CRUD in `process_map_api.py`, instance logic in `instance_api.py`)
- **Vue component**: Add to `spiff/src/components/`
- **Page/view**: Add to `spiff/src/views/` and register in `router/index.js`
- **bpmn-js module**: Add to `spiff/src/bpmn/`, `spiff/src/renderers/`, or `spiff/src/rules/` and register in `BpmnEditor.vue`'s `additionalModules`
- **Moddle extension**: Add to `spiff/src/moddle/` and register in `BpmnEditor.vue`'s `moddleExtensions`

---

## Troubleshooting

### White Screen on /spiff

1. Run `bench build --app one_bpmn`
2. Clear cache: `bench --site your-site.local clear-cache`
3. Hard refresh browser (Ctrl+Shift+R)

### API "Not Whitelisted" Error

Restart the server after adding new API methods:

```bash
bench restart
```

### BPMN Modeler Not Loading

Check browser console for errors. Common fixes:

- Ensure bpmn-js CSS is imported
- Verify container element has proper dimensions

### XML Import Fails

The app automatically decodes HTML entities in stored XML. If issues persist, check browser console for the decoded XML output.

### SpiffWorkflow Extensions Not Showing

- Verify `bpmn-js-spiffworkflow` is installed: `ls node_modules/bpmn-js-spiffworkflow/`
- Ensure the `spiffworkflow` module and `spiffModdleExtension` are registered in `BpmnEditor.vue`
- Check browser console for import errors

---

## ProsAlly — AI Process Modelling Assistant

ProsAlly is an AI-powered chat assistant embedded in the BPMN editor that helps users create, overwrite, and modify process diagrams through natural language prompts.

### Overview

ProsAlly lives as a collapsible side panel (420 px wide on desktop, full-height bottom sheet on mobile) inside the BPMN editor. It runs a multi-step agent pipeline:

```
User prompt
    │
    ▼
Intent Classifier
    │
    ├─ GENERATE_NEW / OVERWRITE_EXISTING / MODIFY_EXISTING
    │       │
    │       ▼
    │   Confirmer  ──► "I'll draw … Shall I proceed?" + [Yes / No, let me adjust]
    │       │  (confirmed)
    │       ▼
    │   Generator / Modifier  ──► BPMN 2.0 XML ──► canvas
    │
    ├─ AMBIGUOUS / INCOMPLETE
    │       │
    │       ▼
    │   Clarifier  ──► focused question + option buttons
    │
    └─ IRRELEVANT  ──► polite redirect
```

### Intent Classification

| Intent | Trigger | ProsAlly response |
|---|---|---|
| `GENERATE_NEW` | User wants a brand-new process on an empty canvas | Confirms, then generates BPMN |
| `OVERWRITE_EXISTING` | User wants to replace the existing model entirely | Confirms, then regenerates |
| `MODIFY_EXISTING` | User wants to add/remove/change a specific part | Confirms, then patches XML |
| `AMBIGUOUS` | Multiple valid interpretations | Asks a clarifying question with options |
| `INCOMPLETE` | Clear intent but missing details | Asks for the missing information |
| `IRRELEVANT` | Nothing to do with process modelling | Redirects politely |

### Key Files

| File | Purpose |
|---|---|
| `spiff/src/components/ProsAllyPanel.vue` | Chat UI — messages, option buttons, rich-text input |
| `spiff/src/components/BpmnEditor.vue` | Panel integration, toggle button, mobile bottom-sheet |
| `spiff/src/utils/bpmnLayout.js` | Auto-layout algorithm — positions generated BPMN elements left-to-right |
| `spiff/src/linting/bpmnlintrc.js` | bpmnlint rule configuration (errors vs. warnings) |
| `one_bpmn/api/process_map_api.py` | Frappe API endpoints for process model CRUD |
| `one_bpmn/api/compilation.py` | Compile/deploy/disable process models |
| `one_bpmn/agents/google_adk/prosally_agent/prosally_agent.py` | LLM agent — intent classification, clarification, generation, modification |
| `one_bpmn/utils/chat_persistence.py` | Persists conversation history in `Chat Conversation` DocType |

### Agent Pipeline (Python)

The `ProsAllyAgent` class in `prosally_agent.py` runs fully async:

1. **IntentClassifier** — calls the LLM with a structured prompt, expects `{"intent": "...", "reason": "..."}`.
2. **Clarifier** — for `AMBIGUOUS`/`INCOMPLETE`, returns `{"question": "...", "options": [...]}`.
3. **Confirmer** — for actionable intents, returns `{"summary": "...", "question": "..."}`.
4. **Generator** — produces complete BPMN 2.0 XML from scratch.
5. **Modifier** — receives existing canvas XML and a patch instruction, returns updated XML.

All LLM responses are parsed via `_parse_json_response()` which strips markdown code fences before calling `json.loads`, with a fallback that extracts the first `{...}` block from the raw response.

### Auto-Layout (`bpmnLayout.js`)

When ProsAlly generates or modifies a diagram, the raw XML uses placeholder coordinates. The layout function:

- Uses `DOMParser` **read-only** to extract element types, IDs, and sequence flow connections.
- Runs a BFS + join-relaxation algorithm to assign left-to-right column positions.
- Builds the entire `<bpmndi:BPMNDiagram>` section as a **plain string** with hardcoded namespace prefixes — never using `XMLSerializer` — to prevent namespace prefix mangling that causes bpmn-moddle reference resolution failures.
- Reads the actual `<bpmn:process id="...">` value and uses it as `BPMNPlane bpmnElement`, ensuring it always matches.
- Assigns correct element dimensions: events 36×36, gateways 50×50, tasks 100×80.
- Adds `isMarkerVisible="true"` on exclusive gateway shapes.
- Routes edges with straight connectors (same row), Manhattan L-routing (different rows), and top-arc routing (back-edges / loop-backs).

### BPMN Generator Rules

The generator LLM is instructed to produce BPMN 2.0 that satisfies all active bpmnlint rules:

- Fixed `id="Process_1"` on `<bpmn:process>` and matching `bpmnElement="Process_1"` on `<bpmndi:BPMNPlane>` — eliminates `no-bpmndi` errors from ID mismatch.
- Exclusive gateways use a `default="Flow_..."` attribute on the gateway and `<bpmn:conditionExpression>` on every non-default outgoing flow — eliminates `conditional-flows` warnings.
- Separate DI placeholder dimensions per element type match the layout algorithm's `DIMS` table.

### LLM Configuration

ProsAlly's LLM provider, model, and API key are configured per-agent in the **Processa Agent LLM Config** child table of the **AI Agent Configuration** DocType. The `agent_id` must match `"prosally_agent"`. Supported providers: `anthropic`, `gemini`, `openai`.

### Conversation Persistence

Each chat session is stored as a `Chat Conversation` record with `agent_mode="ProsAlly"`. The last 30 messages are loaded as context on each turn. The `conversation_name` is returned from the backend and stored in the frontend session, enabling multi-turn coherent conversations.

### Active Linting Rules

| Rule | Severity | Description |
|---|---|---|
| `start-event-required` | Error | Process must have a start event |
| `end-event-required` | Error | Process must have an end event |
| `no-disconnected` | Error | All elements must have at least one connection |
| `single-blank-start-event` | Error | Exactly one blank (untyped) start event |
| `no-bpmndi` | Error | Every semantic element must have DI (BPMNShape/BPMNEdge) |
| `conditional-flows` | Warning | Gateway outgoing flows must have conditions or a default |
| `no-overlapping-elements` | Warning | Shapes must not overlap |
| `label-required` | Warning | Elements should have names |
| `no-implicit-split` | Warning | Tasks should not have multiple outgoing flows |
| `superfluous-gateway` | Warning | Gateways with only one path |
| `no-gateway-join-fork` | Warning | Gateways should not both join and fork |

### Example Prompts

**Generate new process:**
> "Create a leave request approval process. It starts when an employee submits a leave request. A line manager reviews it and either approves or rejects it. If approved, HR updates the records and the process ends. If rejected, the employee is notified and the process ends."

**Modify existing process (canvas must have a diagram loaded):**
> "Add a 'Send Confirmation Email' task after the 'Approve Request' step."

**Overwrite existing:**
> "Scrap the current model and redraw the entire process from scratch based on the new SOP."

---

## License

MIT


## Running Tests

Run the full app test suite from bench:

```bash
bench --site <site> run-tests --app one_bpmn --failfast
```

## Contributing

1. Branch from `staging`
2. Keep changes scoped to the work item
3. Open PRs back to `staging`
4. Prefer small, reviewable changes

## Architecture Overview

- `one_bpmn/api/` exposes backend endpoints organized into domain-specific submodules
- `one_bpmn/api/process_map_api.py` handles diagram CRUD, import/export, and process listing
- `one_bpmn/api/compilation.py` handles compile, deploy, and disable operations
- `one_bpmn/tasks.py` handles scheduled timer-related processing
- `one_bpmn/one_bpmn/doctype/` contains BPMN doctypes and server logic
- `spiff/` contains the frontend BPMN editor

## BPMN Data Model

Primary concepts:
- Process Model
- Process Instance
- Activity Log
