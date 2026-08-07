# ONE-FM AG-UI extension event contract (WI-001671)

Every non-text thing a chat agent may send to a screen, defined once, as data.

## The layering

The AG-UI protocol (`ag-ui-protocol==0.1.10`) defines **26 standard event
types** — run lifecycle, text messages, thinking, tool calls, state — and
**no UI components**. Everything ONE-FM-specific rides in `CustomEvent` with
a name from the `onefm.*` namespace, defined in `schemas/events.json`.

Rules that keep uniformity from drifting:

1. **Non-text information travels only as typed `onefm.*` CustomEvents** —
   never as JSON inside message text, never as bare named SSE lines.
2. **Cards render and request; the host surface applies.** A card's action
   goes through the panel event bus; the host (editor, canvas, builder,
   form) performs the mutation. That is what makes every card testable from
   a recorded fixture.
3. **Errors surface only as the standard `RunError`.** Keep-alives are SSE
   comments — transport, not events.
4. **An unknown `onefm.*` name fails the conformance build** (WI-001680)
   and renders as a safe fallback in the panel — never a broken transcript.

## The events

See `schemas/events.json` — each entry carries its producers, JSON Schema,
a recorded example, and rendering notes. Summary:

| Event | Producer | Rendered as |
|---|---|---|
| `onefm.choice` | any agent | option buttons (panel) |
| `onefm.proposed_config` / `onefm.proposed_update` | AI Assistant | ProposalCard |
| `onefm.script_diff` | Logix | ScriptDiffCard |
| `onefm.test_cases` | Logix | TestCaseCard |
| `onefm.bpmn_preview` | ProsAlly | DiagramPreviewCard |
| `onefm.doctype_schema` | Docu | DocTypeSchemaCard |
| `onefm.table` | any agent | DataTable |
| `onefm.conversation_title` | any agent | header title (panel chrome) |
| `onefm.mode_transition` | Lumina modes | mode chip (panel chrome) |
| `onefm.lucrusher_result` | LuCrusher | one-ai surface |

Explicitly **not** contract events: heartbeats (transport comments) and
`get_page_snapshot` (becomes a standard AG-UI client-side tool call).

## Using it

```python
from one_bpmn.agents import agui_contract

agui_contract.list_events()
agui_contract.validate_event("onefm.choice", value)   # [] when valid
agui_contract.validate_examples()                     # contract self-check
```

`translators.py` derives these events from the legacy per-agent reply dicts
at the shared-stream boundary, so the panel consumes only contract events
even before each agent's migration story lands.
