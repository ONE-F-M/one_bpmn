# Logix – Script Task Agent — export bundle

Processa export of the **Logix – Script Task Agent** process model, delivered via
the export/import route (not a migration patch). Import this on any target site
to get the Logix chat agent with its read-only reference tools.

## Contents

- `diagram.bpmn` — the process model diagram. Carries the ad-hoc "Tools"
  sub-process shapes (the 6 pipeline stages + the 4 read-only reference tools:
  `reference_database`, `get_server_script`, `get_server_script_meta`,
  `list_api_server_scripts`), plus the AI Agent Task's `aiSystemPrompt`,
  `aiToolParams`, and `aiMaxToolCalls`.
- `config.json` — the model's referenced configuration records
  (`export_bpmn_config`): every referenced Server Script (full source),
  Workflow States, and Workflow Action Masters.

## Import steps (on the target site)

1. **Import the diagram** — Processa → Import, select `diagram.bpmn`
   (`one_bpmn.api.process_map_api.import_bpmn`).
2. **Import the config** — Processa → Import Config, select `config.json`
   (`one_bpmn.api.config_export_import.import_bpmn_config`). Missing Server
   Scripts are created; identical ones are skipped; drifted ones are flagged for
   explicit overwrite (`confirm_overwrite_scripts`) — live edits are never
   silently clobbered.
3. **Deploy the model** — this recompiles the diagram, embeds the tool shapes
   into the AI Agent Task's `aiToolShapes`, and enables the linked scripts.
   Import alone does **not** recompile; the Deploy step is required.

## Regenerating this bundle

From the source (BA/dev) site:

```python
import frappe, json
from one_bpmn.api.config_export_import import export_bpmn_config
xml = frappe.db.get_value("BPMN Process Model", "Logix – Script Task Agent", "bpmn_xml")
open("diagram.bpmn", "w").write(xml)
open("config.json", "w").write(json.dumps(export_bpmn_config(xml), indent=2))
```
