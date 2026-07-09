# Durable AI Agent Task — Human-in-the-Loop (HITL)

The AI Agent Task can call a **User or Manual task as a tool**. When the model
selects a human tool, the agent **suspends** — its full conversation is
checkpointed to the database — and the chosen shape is spawned as a real
pending task for its assignee. When the person completes it, the agent
**resumes** in a background AI job with the person's output injected as the
tool call's result, continues reasoning (more tools, another human pause, or a
final answer), and on the final answer the flow continues past the agent task.

## How to model it

1. Model an **AI Agent Task** (`ai_agent`) and point its **Tools: Ad-hoc
   sub-process ID** at an ad-hoc sub-process containing the tool shapes.
2. Inside the tools sub-process:
   - **Script/Service tasks** are automatic tools — they execute inline during
     the agent's reasoning loop, exactly as before.
   - **User/Manual tasks** are **human tools**. Give each one:
     - a **name** — becomes the pending task's title,
     - a **documentation** — becomes the tool description the model sees,
     - an **assignee** (any assignment mode real User Tasks support),
     - optional **task actions** (e.g. `Approve,Reject`) — validated on
       completion like any user task,
     - optional `spiffworkflow:aiToolParams` — the argument schema the model
       fills when calling the tool. Without it the tool takes one `request`
       argument: the message the model writes for the person.
3. Prompt the agent so it knows when to involve a person (see the demo's
   system prompt).

A runnable example is in [examples/durable-ai-agent-hitl-demo.bpmn](examples/durable-ai-agent-hitl-demo.bpmn)
(create a Server Script named `HITL Demo Check Balance` with
`result["balance"] = "120 KWD"` or similar before deploying).

## What users see

- The assignee gets the spawned task as a normal pending action (active
  tasks / ToDo), with the model's request in the task's audit log.
- The instance page shows an amber **"AI agent waiting for a human task —
  X"** banner, and the suspended agent shape pulses amber on the diagram
  (distinct from the purple "Waiting for AI execution" state).
- Completing the task (with its action + any form data) hands the output to
  the agent; the AI Run tab records it as a tool step, so the full
  conversation — including the human's answer — is auditable end to end.

## Behaviour and guarantees

- **Durable**: the checkpoint (conversation, pending call, counters) lives on
  the AI Agent Run row (`status=Suspended`) and survives restarts,
  migrations and long waits.
- **Exactly-once resume**: claiming the checkpoint is atomic; job redelivery
  or a double submit is a no-op.
- **Reject is an answer, not an error**: whatever the person submits
  (`Approve`, `Reject`, form fields) is returned to the model as the tool
  result — the agent reasons about it and concludes accordingly.
- **Not a failure state**: suspension consumes no retries (`aiMaxRetries`)
  and never triggers `aiStopOnError`. The concurrency gate is released while
  waiting, so other pending actions on the instance stay usable.
- **Limits**: `aiMaxToolCalls` caps total model calls across suspensions.
  One human pause at a time — if the model requests two human tools in one
  turn, the second is answered with a "one at a time" tool result.
- **Evidence**: `{tool}_toolCallResult` variables and the aggregated
  `aiToolCallResults` include every segment's results plus the human answer,
  so downstream gateways can route on them.

## Agent-with-HITL vs. AI Task Selector

Both put a human inside an AI-driven flow — pick by shape:

| | **AI Agent Task + human tool** | **AI Task Selector** |
|---|---|---|
| Model | One agent reasons across a single conversation, pausing mid-thought for a person | The AI picks the next process step; the engine runs it; the AI picks again |
| Human step is | A tool call inside the agent's reasoning | A real activated step of the ad-hoc sub-process |
| Best when | "Gather data with tools, ask a person mid-reasoning, then conclude with one answer" | The work IS a sequence of process steps (human and automatic) chosen dynamically |
| Output | One final LLM answer (plus tool evidence) | The sub-process's completed steps |
| Cost | Each resume replays the conversation (context length drives tokens) | Each decision is a fresh, smaller prompt |

If you don't specifically need the *agent pauses mid-reasoning* shape, the
Selector is usually the cheaper, simpler answer.
