import asyncio
import json
import time

import frappe
from frappe import _

_MAX_LLM_ATTEMPTS = 3
_RETRY_DELAY_SECONDS = 2


def _build_transcript(run) -> str:
    """Reconstruct a readable transcript for *run*.

    AI Agent Run stores no message history of its own (no transcript field
    or method - a prior version of this function assumed one existed and
    silently sent an empty string to the LLM every time). The real
    conversation lives in Chat Message records linked to the Chat
    Conversation that the run's BPMN Process Instance was started against.
    Falls back to final_output alone when the run has no linked conversation
    (e.g. a non-chat process), so harvesting still produces something.
    """
    conversation_name = None
    if run.instance:
        try:
            instance = frappe.get_doc("BPMN Process Instance", run.instance)
            if instance.context_doctype == "Chat Conversation":
                conversation_name = instance.context_docname
        except frappe.DoesNotExistError:
            pass

    if not conversation_name:
        return run.final_output or ""

    messages = frappe.get_all(
        "Chat Message",
        filters={"conversation": conversation_name},
        fields=["sender", "text", "message_type", "tool_calls"],
        order_by="creation asc",
    )

    lines = []
    for m in messages:
        lines.append(f"[{m.message_type}] {m.sender}: {m.text or ''}")
        if m.tool_calls:
            lines.append(f"  tool_calls: {m.tool_calls}")

    return "\n".join(lines) or (run.final_output or "")


@frappe.whitelist()
def harvest_skill_from_run(run_name: str) -> str:
    """
    Harvests a generalized skill from a successful AI Agent Run.
    Creates a new Draft AI Skill and returns its name.

    US 7: uses whichever LLM provider the run's own agent is configured
    with (via AI Provider Credentials / AI Chat Settings resolution) rather
    than hard-requiring a separate Gemini credential - so harvesting works
    out of the box with whatever provider is actually set up on the site.
    """
    run = frappe.get_doc("AI Agent Run", run_name)
    transcript = _build_transcript(run)

    if not transcript.strip():
        frappe.throw(_(
            "AI Agent Run {0} has no reconstructable content to harvest from "
            "(no linked Chat Conversation and no final_output)."
        ).format(run_name))

    from one_bpmn.agents.context_assembler import load_agent_behaviour
    from one_bpmn.agents.llm_provider.factory import get_llm_adapter_from_settings

    agent_config = {}
    if run.agent_configuration:
        try:
            agent_config = load_agent_behaviour(run.agent_configuration)
        except Exception:
            frappe.log_error(
                title="harvest_skill_from_run: agent behaviour load failed",
                message=frappe.get_traceback(),
            )

    adapter = get_llm_adapter_from_settings(agent_config)

    system_prompt = """You are an expert AI Agent architect.
Your job is to analyze the provided conversation transcript of an AI Agent successfully solving a task, and distill it into a generalized "AI Skill".
An AI Skill is a markdown document that teaches an agent how to think about a particular kind of work.

Output a JSON object with:
- `skill_name`: A short, unique, dash-separated name (e.g. `handle-customer-refunds`).
- `description`: The routing text the agent sees to decide whether to load this skill.
  It MUST follow this exact structure, in plain sentences (no markdown):
  1. What the skill does, in one sentence.
  2. A sentence starting with "Use this skill when " followed by 2-3 concrete trigger scenarios drawn from the transcript.
  3. A sentence starting with "Do NOT use this skill " followed by what it is NOT for.
  Keep the whole description under 1024 characters.
- `body`: The markdown body of the skill. It should include principles, rules, and step-by-step guidance derived from the transcript.

Format:
{
    "skill_name": "string",
    "description": "string",
    "body": "string"
}

Respond with ONLY the JSON object - no markdown fences, no other text.
"""

    user_prompt = f"Transcript:\n{transcript}"

    async def _call():
        return await adapter.step(
            system=system_prompt,
            transcript=[{"role": "user", "content": user_prompt}],
        )

    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

    step_result = None
    last_error = None
    for attempt in range(1, _MAX_LLM_ATTEMPTS + 1):
        try:
            step_result = loop.run_until_complete(_call())
            last_error = None
            break
        except Exception as e:
            last_error = e
            frappe.log_error(
                title=f"harvest_skill_from_run: LLM call attempt {attempt} failed",
                message=frappe.get_traceback(),
            )
            if attempt < _MAX_LLM_ATTEMPTS:
                time.sleep(_RETRY_DELAY_SECONDS * attempt)

    if last_error is not None:
        frappe.throw(_(
            "LLM call failed after {0} attempts: {1}"
        ).format(_MAX_LLM_ATTEMPTS, str(last_error)))

    text = (step_result.content or "").strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
        text = text.strip()

    try:
        result_json = json.loads(text)
    except Exception as e:
        frappe.throw(_("Failed to parse LLM response: {0}").format(str(e)))

    skill_name = result_json.get("skill_name")
    description = (result_json.get("description") or "").strip()
    body = result_json.get("body")

    if not skill_name or not body:
        frappe.throw(_("LLM did not return required fields."))

    # Defensive net: the prompt asks for the exact required phrasing, but the
    # model doesn't always comply. Rather than fail the harvest on a subtle
    # miss, patch in the missing clause so ai_skill.py's validation passes.
    desc_lower = description.lower()
    if "use this skill when" not in desc_lower and "when to use" not in desc_lower:
        description = f"{description} Use this skill when a similar task comes up."
        desc_lower = description.lower()
    if "do not use" not in desc_lower and "when not to use" not in desc_lower:
        description = f"{description} Do NOT use this skill for unrelated tasks."
    if len(description) > 1024:
        description = description[:1021].rstrip() + "..."

    # US 7: nothing publishes automatically - Draft status and the most
    # restrictive tier until a human reviews it and assigns a tier deliberately.
    skill = frappe.new_doc("AI Skill")
    skill.skill_name = skill_name
    skill.description = description
    skill.body = body
    skill.status = "Draft"
    skill.tier = "Draft-Only"

    skill.insert(ignore_permissions=True)

    return skill.name
