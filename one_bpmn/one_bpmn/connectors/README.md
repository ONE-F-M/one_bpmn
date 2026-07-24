# BPMN Service Task Connectors

A **connector** lets a BPMN Service Task call an external provider's API through
configuration on the element — no Script Task, no hand-written integration code
in the diagram. It is the `one_bpmn` analogue of Camunda's outbound connectors.

## How it runs

```
<bpmn:serviceTask spiffworkflow:serviceType="connector"
                  spiffworkflow:connectorId="google_drive"
                  spiffworkflow:operation="createFile"
                  spiffworkflow:connectorParams="{ ...json... }"
                  spiffworkflow:resultVariable="drive_file"
                  spiffworkflow:failOnError="false" />
```

At runtime the engine leaves the Service Task `STARTED`; `_dispatch_service_task`
routes `serviceType == "connector"` to `dispatch_connector`
(`doctype/bpmn_process_instance/dispatchers.py`), which:

1. parses `connectorParams` (a JSON object),
2. Jinja-renders every field flagged `expression` against `{doc, instance, frappe, task_data}`,
3. normalizes `DriveFile`/`DriveFolder` fields (accepts a share link **or** a bare id),
4. calls the registered handler `(connectorId, operation) → fn(params, ctx)`,
5. writes the handler's dict return to `task.data[resultVariable]`.

Errors are logged and non-fatal by default; set `failOnError` to re-raise and
mark the instance **Errored**.

## Three layers (data ⇄ code ⇄ UI)

| Layer | Where | Purpose |
|---|---|---|
| **Registry** | `connectors/registry.py` | `@connector(id, op)` → handler map (runtime dispatch) |
| **Manifest** | `connectors/manifests/<id>.json` | operations + fields (drives the modeler UI *and* runtime field handling) |
| **Handler** | `connectors/<id>_ops.py` | thin wrapper over `integrations/<provider>.py` |

The manifest is a faithful projection of the provider's real API: operations =
API methods, field enums/required-ness = the API's own. `validator.py` enforces
manifest⇄handler parity (run in the test suite).

## Adding a connector

1. **Integration module** `integrations/<provider>.py` — real API calls, built on
   `google_common` (`get_service`, `call_with_retry`, `normalize_drive_id`).
2. **Handlers** `connectors/<provider>_ops.py` — `@connector("<id>", "<op>")`
   functions taking `(params, ctx)` and returning a JSON-safe dict.
3. **Manifest** `connectors/manifests/<id>.json` — see field schema below.
4. **Register** — import the ops module in `connectors/__init__.py`.

No engine or frontend change is needed — the panel renders any manifest.

### Manifest field schema

```jsonc
{ "name": "file", "label": "File", "type": "String|Text|Dropdown|Boolean|DriveFile|DriveFolder",
  "required": true, "expression": true, "default": "",
  "choices": [{ "label": "...", "value": "..." }],   // static Dropdown enum
  "choicesFrom": "driveDocumentTypes",                // OR dynamic dropdown (backend get_connector_field_choices)
  "condition": { "field": "type", "equals": "user" }, // OR "oneOf": [...]  — conditional visibility
  "help": "shown under the field" }
```

- `expression: true` (default) — value is Jinja-rendered at runtime.
- `DriveFile`/`DriveFolder` — link-or-id normalized before the handler runs.
- `condition` — field only shows when another field/`operation` matches.
- `choicesFrom` — options fetched live from
  `connectors/api.get_connector_field_choices(source)`.

## Shipped connectors

- **google_drive** — downloadText, createFile, updateFileContent, setPermissions, listFiles, deleteFile
- **google_docs** — createDocument, insertText, appendText, replaceAllText, getText
- **google_slides** — createPresentation, replaceAllText, createSlide, duplicateSlide, getText

## Credentials

A single service-account JSON in `AI Chat Settings` (fallbacks: `site_config.json`,
`private/files/gcp.json`) — see `google_common.load_service_account_info`. Business
config (files, folders, templates) lives **on the element**, never in settings.

## Not yet done (future)

- Reconcile manifests against Google's live API discovery documents (network).
- BPMN Error boundary-event mapping for `failOnError` (currently errors the instance).
