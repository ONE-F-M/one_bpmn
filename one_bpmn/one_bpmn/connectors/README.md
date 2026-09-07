# BPMN Service Task Connectors

A **connector** lets a BPMN Service Task call an external provider's API through
configuration on the element — no Script Task, no hand-written integration code
in the diagram. It is the `one_bpmn` analogue of Camunda's outbound connectors.

**Connectors are configuration, not code.** A whole connector — its label, canvas
icon, operations, the fields each operation shows, which are required, their
dropdown choices and conditional visibility, and how the call is actually made —
is authored in the desk UI:

```
BPMN Connector  →  BPMN Connector Operation  →  BPMN Connector Field (child table)
```

A connector that talks plain HTTP/REST needs **no Python at all**.

> **New to this?** [WALKTHROUGH.md](WALKTHROUGH.md) walks through building one
> field by field, twice — once for an HTTP connector (no code) and once for a
> Python Handler connector.

## How it runs

```xml
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

1. resolves the executor for `(connectorId, operation)` — see below,
2. parses `connectorParams` (a JSON object),
3. Jinja-renders every field flagged `expression` against `{doc, instance, frappe, task_data}`,
4. applies each field's configured **Value Transform**, if it declares one,
5. calls the executor with `(params, ctx)`,
6. writes its dict return to `task.data[resultVariable]`.

Errors are logged and non-fatal by default; set `failOnError` to re-raise and
mark the instance **Errored**.

### Executor resolution

`_resolve_connector_handler` consults the configuration first, in order:

1. the operation's **Handler Path** — an explicit dotted path to `fn(params, ctx)`
2. execution type **HTTP Request** → `http_ops.execute` (declarative, no Python)
3. the **`@connector` registry** — the shipped SDK-backed handlers (Google)

Step 3 also covers "no configuration row exists", so a code-only connector keeps
working unchanged.

## Where each layer lives

| Layer | Where | Purpose |
|---|---|---|
| **Configuration** | `BPMN Connector` / `… Operation` / `… Field` DocTypes | the live definitions — operations, fields, icons, execution |
| **Loader** | `connectors/manifest.py` | projects the DocTypes into manifest dicts (cached); serves the modeler *and* runtime field handling |
| **HTTP executor** | `connectors/http_ops.py` | renders and performs a configured request; maps the response |
| **Registry** | `connectors/registry.py` | `@connector(id, op)` → handler map, for SDK-backed providers |
| **Handler** | `connectors/<id>_ops.py` | thin wrapper over `integrations/<provider>.py` |
| **Seed** | `connectors/manifests/<id>.json` | shipped starting point, imported into the DocTypes on migrate |

`validator.py` enforces that every operation a modeler can pick actually resolves
to an executor, and that its fields are well-formed. It runs in the test suite and
behind **Validate Configuration** on the BPMN Connector form.

## Adding a connector

**REST/HTTP provider — entirely in the desk, no code, no rebuild:**

1. **BPMN Connector** — id, label, icon SVG path + colour, Base URL, Auth Type
   and the **Secret** itself (or a pointer to a shared one).
2. **BPMN Connector Operation** per API method — `Method` + `URL Template`,
   optional Query/Headers/Body templates, and a **Response Map** projecting the
   response into the output dict.
3. **Fields** — one row per input the modeler should fill in.

Templates are Jinja; field values are exposed as `params`, alongside `doc`,
`task_data`, `instance` and `frappe`. Example body: `{"name": "{{ params.filename }}"}`.

**SDK-backed provider (OAuth service accounts, resumable uploads, …):**

1. **Integration module** `integrations/<provider>.py` — real API calls, using the
   provider-neutral `integrations/retry.call_with_retry` (Google's own plumbing —
   `get_service`, `normalize_drive_id` — lives in `integrations/google_common.py`).
2. **Handlers** `connectors/<provider>_ops.py` — `@connector("<id>", "<op>")`
   functions taking `(params, ctx)` and returning a JSON-safe dict.
3. Configure the connector as above with execution type **Python Handler**.

Either way the modeler panel and the canvas icon follow automatically — no engine
or frontend change.

### Field schema

| DocType field | Manifest key | Notes |
|---|---|---|
| Field Name | `name` | key inside `connectorParams` |
| Label / Type / Required | `label` / `type` / `required` | type ∈ String, Text, Dropdown, Boolean, Hidden — the widget, nothing more |
| Expression | `expression` | on (default) → Jinja-rendered at runtime |
| Default Value | `default` | |
| **Value Transform** | *(server-side)* | dotted path to `fn(value) -> value`, run after rendering |
| Choices | `choices` | `Label\|value` per line |
| **Choices From** | `dynamicChoices` | dotted path to `fn(**context) -> [{label, value}]` |
| Only Show When / Operator / Value | `condition` | `equals` or `one of`; the literal `operation` tests the selected operation |
| Help Text | `help` | shown under the field |

### Value Transform — provider quirks without provider code

Nothing in the generic layer knows about any provider. Input normalisation is a
field-level **Value Transform**: a dotted path to `fn(value) -> value` applied
after the expression renders. The Google connectors point their file and folder
fields at `google_common.normalize_drive_id`, which is why you can paste either a
Drive share link or a bare id — that behaviour is *configuration*, not a special
field type. (Before this it was a hardcoded `if type in ("DriveFile",
"DriveFolder")` in the dispatcher.) A transform that raises is logged and the
original value is used, so a bad transform degrades instead of failing the task.

### Choices From — dependent dropdowns

Set a field's **Choices From** to a dotted path returning `[{label, value}]`. The
panel sends the connector, operation and field — never the path, which the server
reads from the configuration — plus the sibling field values as `context`, and the
function receives the ones it declares as keyword arguments. So
`list_file_choices(folder=None)` gets whatever the modeler put in the `folder`
field, and the dropdown lists that folder's contents.

Both paths are validated importable and callable when the operation is saved, and
neither is included in the manifest served to the browser.

### Canvas icon

`Icon SVG Path` is the `d` attribute of one path on a **24×24 viewBox** (paste
from any icon set), with `Icon Colour` as a hex value. The Service Task shows it
in place of the gear; connectors with no icon get the default teal plug. The form
renders a live preview, and the diagram picks it up on the next load — no rebuild.

## Letting the Connector Agent build one

A connector is configuration, which means an agent can author it. The **Connector
Agent** (`connector_agent`) is a *background* agent: an orchestrator
delegates a work order to it over A2A and it builds the connector on its own.

```
orchestrator's ad-hoc sub-process
  └─ Service Task  serviceType=connector  connectorId=a2a
                   operation=delegate_to_local_agent
                   connectorParams={"agent": "Connector Agent",
                                    "instruction": "<what to build, in words>"}
```

`a2a/local.delegate` creates the A2A Task, which starts the agent's own
A2A-startable map (BPMN Process Model **Connector Agent**). Its answer comes back
on the task's `result`, and the connector rows appear in the desk.

The work order is plain English. It may name an **OpenAPI/Swagger URL**, a
**documentation page**, an example **curl**, or simply describe the API — the agent
uses whichever it is given.

The agent's tool shapes live in the map; the mechanics live in `authoring.py`:

| Tool | Does |
|---|---|
| `read_api_docs` | fetches the spec or docs page, guarded exactly like a connector call (https only, no internal hosts, size-capped) |
| `draft_connector` | with a spec, builds the manifest **mechanically** — path parameters become required fields and the URL template is generated to reference exactly those fields; without one, drafts from the prose via the `connector_writer` sub-prompt |
| `review_connector` | `validate_manifest` — the deterministic gate, see below |
| `write_connector` | imports the manifest **disabled** |
| `test_operation` | runs ONE operation through the real `http_ops.execute`, so "it works" is observed rather than claimed |

Two properties make an agent-authored connector safe to accept:

- **It is written disabled.** The rows are real, so a person can read, test and fix
  them in the desk, but the modeler will not offer the connector and dispatch
  refuses it until a human ticks **Enabled**. A draft never carries a secret, so
  enabling is also the moment someone has to supply the credential — the review is
  structurally unavoidable rather than merely recommended.
- **The review is deterministic, not another LLM.** `validate_manifest` checks a
  draft *before* it is written and catches what an LLM-authored connector actually
  gets wrong: a template referencing a field that was never declared,
  `params.values` resolving to the dict method, a relative URL with no Base URL, a
  body that stops being JSON once the expressions are filled in, a `{{ doc.x }}`
  that will render the literal `None`, and a secret that has no business being in a
  manifest at all.

`validate_manifest` and the importer must agree about the manifest dialect — the
executable half of an operation is a nested `http` block (`url`, `query`, `headers`,
`contentType`, `body`, `responseMap`), never a parallel spelling. If they drift,
review approves a draft that then fails to import, and the agent re-drafts a
perfectly good connector until its tool budget runs out. That invariant is pinned by
`TestReviewerImporterAgreement` in `tests/test_connector_authoring.py`.

`get_execution_spec(..., allow_disabled=True)` exists for this feature: dispatch
must keep refusing a disabled connector, while authoring has to be able to test a
draft before anyone enables it.

## Portability

Connectors move between sites as **data**, not patches:

- `api.export_connector(connector_id)` → JSON manifest (also the **Export JSON**
  button on the form). Secrets never travel — only the settings DocType and
  fieldname that say where to read them.
- `api.import_connector(manifest, overwrite=False)` → creates/updates a connector.

The JSON files in `manifests/` are the shipped seed: the patch
`import_connector_manifests_to_doctype` imports them, skipping any connector that
already exists, so a site's own edits survive a re-run. They are also the fallback
when no connector rows exist (fresh install, bench console with no site).

## Shipped connectors

- **google_drive** — downloadText, createFile, updateFileContent, setPermissions, listFiles, deleteFile
- **google_docs** — createDocument, insertText, appendText, replaceAllText, getText
- **google_slides** — createPresentation, replaceAllText, createSlide, duplicateSlide, getText
- **google_sheets** — createSpreadsheet, getValues, updateValues, appendValues, clearValues, addSheet

## Credentials

Every connector keeps its credential **on the connector**: an encrypted
`Password` field in its Auth section (`Credential Source = On this connector`).
The value goes to Frappe's `__Auth` store, not the doctype column, and appears in
neither the manifest served to the browser nor an export — only the *fact* that a
credential is expected travels.

Google is no exception. Each Google connector holds its own service-account key —
the whole JSON file Google issued, pasted into **Secret** — and
`google_common.load_service_account_info` reads that and nothing else. A caller
that names no connector (the Script Tasks importing `integrations/google_drive`
directly) gets the `google_drive` connector's key. There is **no** settings-level,
`site_config.json` or `private/files/gcp.json` fallback: a global default is
invisible while it works, and with one in place four connectors silently share one
account so pointing one at a second Google project changes nothing. A missing key
is an error naming the connector to fix. That is also why `Secret` is a
10,000-character field — a service-account key is ~2.3kB, and Frappe's Password
control otherwise caps input at 140.

The credential is the *only* Google config anywhere. All business config —
destination **folders**, files, templates — is entered **on the connector
element**, never in settings.

Set `Credential Source = From a settings DocType` instead when several connectors
genuinely share one key and one rotation is worth losing per-connector accounts
for. The target must be a `Password` field; a plain `Data` field is refused on
save.

**Google needs a Shared Drive.** A service account has no My Drive quota, so
anything that creates a file (`createFile`, `createDocument`,
`createPresentation`, `createSpreadsheet`) must target a folder in a Shared Drive
the service account belongs to — which is why all four take a **Folder**.

**`deleteFile` with "Delete permanently" needs a Manager.** On a Shared Drive a
Content Manager cannot purge, and Google answers **404** rather than 403, so the
failure looks like "file not found". Leave the option off to trash instead.

## Outbound-request safety

The HTTP executor refuses non-`http(s)` schemes, and refuses hosts resolving to
loopback / link-local / private / reserved addresses unless the connector ticks
**Allow Internal Hosts** — otherwise a connector doubles as a request forger
against the server's own network. Responses above 2 MB are rejected rather than
written into task data. Transient 429/5xx are retried with backoff via
`google_common.call_with_retry`.

## Expression gotcha

Jinja here behaves as it does everywhere else in Frappe, which means a **field
that is set but empty renders as the literal string `None`** — e.g.
`{"note": "{{ doc.note }}"}` sends `"note": "None"` when `note` is unset. Guard it
in the template: `{{ doc.note or "" }}`.

An **unknown name** is different: Frappe renders it as the debug text
`{{ no such element: … }}`, which would corrupt a URL or body, so the HTTP
executor blanks those. The older `connectorParams` path does not — a typo'd field
name there reaches the provider as that literal string.

## Not yet done (future)

- Reconcile manifests against Google's live API discovery documents (network).
- BPMN Error boundary-event mapping for `failOnError` (currently errors the instance).
- Normalise `None` to empty in both rendering paths (see the gotcha above) — a
  behaviour change to shipped connectors, so deliberately not done here.
