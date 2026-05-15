---
applyTo:
  - "one_bpmn/agents/google_adk/prosally_agent/**"
  - "spiff/src/components/ProsAllyPanel.vue"
  - "spiff/src/utils/bpmnLayout.js"
---

# ProsAlly AI Assistant

This file is intentionally a pointer, not a second full copy of the instructions.

**Canonical source of truth:** `one_bpmn/agents/google_adk/prosally_agent/prosally-agent.instructions.md`

Do not update architecture, intent taxonomy, return-shape keys, layout rules, or prompt guidance here.
Make all instruction changes in the canonical in-tree file above so `.github/instructions` cannot drift from the agent implementation docs.
- `MODIFY_EXISTING` when user names a specific step, task, gateway, lane, or section to add/remove/change.
- Prefer `INCOMPLETE` over `AMBIGUOUS` when uncertain between the two.

## Confirm-Before-Act Protocol

ProsAlly **never acts without user confirmation**. Every action intent (GENERATE_NEW, OVERWRITE_EXISTING, MODIFY_EXISTING) goes through the Confirmer, which writes a 2–4 sentence summary and asks "Shall I proceed?". The frontend stores the `action_intent` on the CONFIRM message. When the user clicks "Yes, proceed", the frontend re-sends with `confirmed_action` set, bypassing classification (STEP 0).

## ProcessGenerator — Prompt Contract

Invoked for `GENERATE_NEW` and `OVERWRITE_EXISTING` (and as fallback for `MODIFY_EXISTING` when no canvas XML is available).

- Input: `_build_generator_prompt(process_name, action_intent, chat_history)`
- Output: raw BPMN 2.0 XML
- Shape coordinates in the LLM output are **placeholders** (`x=150, y=260`) — the layout algorithm replaces all positions.
- Required XML structure: `bpmn:definitions` → `bpmn:process` → semantic elements + `bpmndi:BPMNDiagram` → `bpmndi:BPMNPlane` → shapes + edges.
- Every semantic element must have a `BPMNShape`; every `sequenceFlow` must have a `BPMNEdge`.
- 3–12 elements (excluding flows). Exactly one `startEvent` and one `endEvent`.

## ProcessModifier — Prompt Contract and Patterns

Invoked only for `MODIFY_EXISTING` when `current_xml` is non-empty.

- Input: `_build_modifier_prompt(process_name, chat_history, current_xml)`
- Output: complete modified BPMN 2.0 XML (not a diff — the whole document)
- **IDs of existing elements must never be renamed or re-sequenced.**
- All new elements get globally unique IDs (7 random alphanumeric chars appended).

### Modification Patterns

| Pattern | Description |
|---|---|
| A — Insert Between | `A → C` becomes `A → B → C`: redirect the A→C flow's `targetRef`, add new flow B→C, add shape + edge placeholders. |
| B — Insert Before End | Default when target is not explicit: find the flow into the end event, apply Pattern A through it. |
| C — Add Decision Branch | Insert an `exclusiveGateway` via Pattern A/B; label the main/yes branch; add new task + "no" path; reconnect to end or join. All gateway outbound flows must have `name` attributes. |
| D — Remove Element | Collect predecessors (incoming `sourceRef`) and successors (outgoing `targetRef`); create all `(predecessor, successor)` bridging flows; delete element, its flows, its `BPMNShape`, and its `BPMNEdge` entries. Guards: never remove `startEvent` or `endEvent`. |

### Removal Guards

If asked to remove a `startEvent` or `endEvent`, the modifier outputs the XML unchanged and appends:
```xml
<!-- ProsAlly: cannot remove [element type] — required by BPMN linting rules -->
```

## Layout Post-Processing (`bpmnLayout.js`)

After every `BPMN_GENERATED` or `BPMN_MODIFIED` response, `BpmnEditor.onProsAllyBpmnGenerated()` calls `layoutBpmnXml(xml)` before passing to `modeler.importXML()`.

**Algorithm:**
1. Parse XML with `DOMParser`.
2. Collect semantic elements and `sequenceFlow` edges from `bpmn:process`.
3. BFS from `startEvent` to assign column depth.
4. Relax join nodes to max incoming column + 1 (cycle-safe: skip back-edges where `column[source] >= column[target]`).
5. Group by column, centre rows around `y = 300`, spacing `120px` vertically.
6. Horizontal spacing: `160px` centre-to-centre.
7. Overwrite all `BPMNShape` `dc:Bounds` with computed anchors. Create missing `BPMNShape` elements for any semantic element without one (`no-bpmndi` rule compliance).
8. Overwrite all `BPMNEdge` waypoints with Manhattan routing. Create missing `BPMNEdge` elements for flows without one.
9. Return `XMLSerializer().serializeToString(doc)`.

Element dimensions used by the layout:
| Type | Width | Height |
|---|---|---|
| startEvent / endEvent | 36 | 36 |
| userTask / serviceTask / task / scriptTask / manualTask | 100 | 80 |
| exclusiveGateway / parallelGateway / inclusiveGateway | 50 | 50 |
| subProcess | 200 | 120 |

## Return Shape

`run_prosally_message()` always returns a dict:

```python
{
    "intent":        "BPMN_GENERATED" | "BPMN_MODIFIED" | "CONFIRM" | "CLARIFY" | "IRRELEVANT" | "ERROR",
    "action_intent": "GENERATE_NEW" | "OVERWRITE_EXISTING" | "MODIFY_EXISTING" | None,
    "response":      str,          # text shown to user in chat bubble
    "bpmn_xml":      str | None,   # BPMN 2.0 XML (BPMN_GENERATED and BPMN_MODIFIED only)
    "options":       list[str],    # button labels ("Yes, proceed" / "No, let me adjust" / clarification choices)
}
```

## API Endpoint (`api.py`)

| Parameter | Type | Purpose |
|---|---|---|
| `message` | `str` | User's chat message |
| `session_id` | `str` | Client-generated session identifier |
| `chat_history` | `str` (JSON) | Last 10 messages serialised as `[{role, content}]` |
| `process_name` | `str` | Name of the open BPMN process |
| `diagram_name` | `str` | Diagram identifier (passed through) |
| `confirmed_action` | `str` | Set to the `action_intent` when user confirms; bypasses classification |
| `current_xml` | `str` | Full canvas BPMN XML; required for `MODIFY_EXISTING` confirmed actions |

Endpoint: `one_bpmn.api.prosally_chat` (POST, `@frappe.whitelist()`). Raises 403 for Guest users.

## Agent Configuration

- Credentials: read from `AI Chat Settings` DocType (`google_vertex_ai_api_key`, `gemini_model`).
- Sub-prompt overrides: loaded from `AI Agent Configuration` via `get_agent_config("prosally_agent")`.
  Key names: `intent_classifier`, `clarifier`, `confirmer`, `process_generator`, `modifier`, `redirect`.
- Falls back to `_DEFAULT_*_INSTRUCTION` constants if config is absent.

## Frontend (`ProsAllyPanel.vue`, `BpmnEditor.vue`)

- `ProsAllyPanel` is mounted as a **flex sibling** to the canvas container (not absolute) so the canvas naturally shrinks when the panel is open. Mobile shows a 70 vh bottom sheet.
- Props: `processName` (str), `diagramName` (str), `getCanvasXml` (async function → str).
- Emits: `close`, `bpmn-generated` (payload: XML string).
- `selectOption(opt, msgId)`: clears options on the source message; if `msg.intent === "CONFIRM"` and `opt === "Yes, proceed"`, extracts `msg.action_intent` as `confirmedAction`.
- `sendMessage(opts)`: when `opts.confirmedAction === "MODIFY_EXISTING"`, awaits `props.getCanvasXml()` and includes result as `current_xml` in the POST body.
- On `BPMN_GENERATED` or `BPMN_MODIFIED` response: emits `bpmn-generated` with `result.bpmn_xml`.
- `BpmnEditor.onProsAllyBpmnGenerated(xml)`: calls `layoutBpmnXml(xml)` then `loadXML(laidOut)` then emits `changed`.
- `BpmnEditor.getCanvasXml()`: calls `modeler.saveXML({ format: false })` and returns the XML string.

## Linting Compliance

Active bpmnlint rules the pipeline must respect (from `src/linting/bpmnlintrc.js`):

| Rule | Severity | How ProsAlly satisfies it |
|---|---|---|
| `start-event-required` | error | Generator always includes a `startEvent`. Modifier guards against removing it. |
| `end-event-required` | error | Generator always includes an `endEvent`. Modifier guards against removing it. |
| `no-bpmndi` | error | `layoutBpmnXml` creates missing `BPMNShape` / `BPMNEdge` for every element. |
| `no-disconnected` | error | Generator instruction requires all elements connected. Modifier bridges flows on removal. |
| `no-overlapping-elements` | warn | `layoutBpmnXml` ensures non-overlapping positions via column/row spacing. |
| `label-required` | warn | All generator/modifier instructions require descriptive `name` attributes. |
| `conditional-flows` | warn | Gateway outbound flows must have `name` attributes (enforced in Patterns C and D). |

## Review Checklist

- `_extract_bpmn_xml()` must be called on every generator/modifier output before returning `bpmn_xml`. It strips markdown fences the LLM may add.
- `_run_agent()` may return `None` (no final event). All callers guard against `None` with `or ""`.
- `run_prosally_message()` is synchronous (`asyncio.run()`). Never call it from inside an already-running event loop.
- `InMemorySessionService` sessions must be deleted in the `finally` block of `process_message()`.
- `confirmed_action` in STEP 0 must be in `_ACTION_INTENTS` before acting — never trust an unvalidated string from the client.
- `current_xml` for `MODIFY_EXISTING` is sent by the client; treat it as untrusted input (do not execute it server-side).
- The layout utility returns the original XML unchanged on `parsererror` — callers must handle a potentially un-relaid diagram gracefully.
