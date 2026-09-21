import frappe
from one_bpmn.agents.llm_provider.base import ToolSpec
from frappe.utils import now_datetime
import hashlib


def _conversation_id(instance):
    """The Chat Conversation this instance's turn belongs to, or None.

    Skill activation is scoped to the CONVERSATION, not the process
    instance: a resumed conversation gets a brand new instance (see
    agents/memory/session_state.py), so state keyed by instance.name cannot
    survive the conversation it was loaded for. A skill loaded on turn one
    would vanish the moment the map re-armed through its conditional start.
    """
    if not instance:
        return None
    if getattr(instance, "context_doctype", "") == "Chat Conversation":
        return getattr(instance, "context_docname", None)
    return None


def _turn_counter_key(conversation):
    return f"ai_skill_turn_{conversation}"


def current_turn(conversation) -> int:
    """The turn number to attribute a load/unload to, starting at 1.

    A lightweight counter in the same cache as the activation state, rather
    than a new doctype field on the instance \u2014 nothing else needs this
    number, so nothing else should have to carry it.
    """
    if not conversation:
        return 0
    value = frappe.cache().get_value(_turn_counter_key(conversation))
    return int(value or 1)


def advance_turn(conversation) -> int:
    """Bump and return the turn counter. Called once per dispatched turn."""
    if not conversation:
        return 0
    nxt = current_turn(conversation) + 1
    frappe.cache().set_value(_turn_counter_key(conversation), nxt)
    return nxt


def _skills_cache_key(conversation, agent_name):
    """Loaded skill bodies, scoped to the conversation AND the agent.

    Logix runs several agents inside one conversation (the orchestrator, the
    classifier, the writers). A contract the writer loaded must reach the
    writer's next turn, not the classifier's.
    """
    return f"active_skills_{conversation}_{agent_name}"


def _skill_names_cache_key(conversation, agent_name):
    return f"active_skill_names_{conversation}_{agent_name}"


def clear_conversation_skills(conversation):
    """Drop all loaded-skill state for a conversation.

    Called when a conversation closes so a fresh conversation with the same
    (or a different) instance never inherits skills it never loaded.
    """
    if not conversation:
        return
    frappe.cache().delete_keys(f"active_skills_{conversation}_")
    frappe.cache().delete_keys(f"active_skill_names_{conversation}_")
    frappe.cache().delete_value(_turn_counter_key(conversation))


def log_activation(skill_name, agent_name, instance=None, turn_loaded=None):
    if not instance:
        return

    conversation = _conversation_id(instance)

    agent_run = None
    if instance:
        runs = frappe.get_all("AI Agent Run", filters={"instance": instance.name}, fields=["name"], order_by="creation desc", limit=1)
        if runs:
            agent_run = runs[0].name

    # We can hash the agent name and skill name as a proxy for prompt hash
    prompt_hash = hashlib.md5(f"{agent_name}_{skill_name}".encode()).hexdigest()

    try:
        frappe.get_doc({
            "doctype": "AI Skill Activation",
            "skill": skill_name,
            "agent_configuration": agent_name,
            "agent_run": agent_run,
            "conversation": conversation,
            "prompt_hash": prompt_hash,
            "loaded_at": now_datetime(),
            "turn_loaded": turn_loaded if turn_loaded is not None else current_turn(conversation),
        }).insert(ignore_permissions=True)
        frappe.db.commit()
    except Exception as e:
        frappe.log_error(f"Failed to log AI Skill Activation: {e}")


def log_deactivation(skill_name, conversation, turn_unloaded=None):
    """Mark the most recent still-open activation of *skill_name* as unloaded.

    "Still open" means it has a loaded_at and no unloaded_at yet \u2014 the row a
    matching load_skill call created.
    """
    if not conversation:
        return
    rows = frappe.get_all(
        "AI Skill Activation",
        filters={"skill": skill_name, "conversation": conversation, "unloaded_at": ["is", "not set"]},
        fields=["name"],
        order_by="creation desc",
        limit=1,
    )
    if not rows:
        return
    try:
        doc = frappe.get_doc("AI Skill Activation", rows[0].name)
        doc.unloaded_at = now_datetime()
        doc.turn_unloaded = turn_unloaded if turn_unloaded is not None else current_turn(conversation)
        doc.save(ignore_permissions=True)
        frappe.db.commit()
    except Exception as e:
        frappe.log_error(f"Failed to log AI Skill deactivation: {e}")


def get_skill_tools(agent_name, instance=None):

    def check_skill_allowed(skill_name):
        doc = frappe.db.get_value("AI Skill", skill_name, ["status", "body"], as_dict=True)
        if not doc:
            return False, "Skill not found."

        # US 3: unpublished (Draft) or Deprecated skills are refused.
        if doc.status != "Active":
            return False, f"Skill is not published (status: {doc.status})."

        # Check if skill is enabled for agent
        is_enabled = frappe.db.count("AI Agent Enabled Skill", {"parent": agent_name, "skill": skill_name}) > 0
        if not is_enabled:
            return False, "Skill is not enabled for this agent."

        return True, doc

    def load_skill(skill_name: str) -> str:
        """Load the full instructions body of a published AI Skill.
        Args:
            skill_name: The exact name of the skill from the index.
        """
        allowed, result = check_skill_allowed(skill_name)
        if not allowed:
            return f"Error: {result}"

        conversation = _conversation_id(instance)
        log_activation(skill_name, agent_name, instance)

        # Skill state is scoped to the CONVERSATION, not the process instance
        # (a resumed conversation gets a brand new instance, so state keyed
        # by instance.name would never survive a resume). Written to Frappe
        # cache so the dispatcher can pick it up on the NEXT loop/turn and
        # actually put the body in front of the model.
        if conversation:
            cache_key = _skills_cache_key(conversation, agent_name)
            active = frappe.cache().get_value(cache_key) or []
            if result.body not in active:
                active.append(result.body)
                frappe.cache().set_value(cache_key, active)

            # Also track the skill names!
            names_key = _skill_names_cache_key(conversation, agent_name)
            active_names = frappe.cache().get_value(names_key) or []
            if skill_name not in active_names:
                active_names.append(skill_name)
                frappe.cache().set_value(names_key, active_names)

        return result.body

    def unload_skill(skill_name: str) -> str:
        """Unload a previously loaded AI Skill.

        Removes its body and tools from the next turn's prompt and tool
        pool. Has no effect on the current turn's already-issued prompt.
        Args:
            skill_name: The exact name of the skill to unload.
        """
        conversation = _conversation_id(instance)
        if not conversation:
            return f"Error: no conversation to unload '{skill_name}' from."

        doc = frappe.db.get_value("AI Skill", skill_name, ["body"], as_dict=True)
        if not doc:
            return f"Error: Skill '{skill_name}' not found."

        cache_key = _skills_cache_key(conversation, agent_name)
        active = frappe.cache().get_value(cache_key) or []
        if doc.body in active:
            active = [b for b in active if b != doc.body]
            frappe.cache().set_value(cache_key, active)

        names_key = _skill_names_cache_key(conversation, agent_name)
        active_names = frappe.cache().get_value(names_key) or []
        was_loaded = skill_name in active_names
        if was_loaded:
            active_names = [n for n in active_names if n != skill_name]
            frappe.cache().set_value(names_key, active_names)

        log_deactivation(skill_name, conversation)

        if not was_loaded:
            return f"Skill '{skill_name}' was not loaded."
        return f"Skill '{skill_name}' unloaded."

    def load_skill_resource(skill_name: str, resource_name: str) -> str:
        """Load a specific resource row attached to an AI Skill.
        Args:
            skill_name: The exact name of the skill.
            resource_name: The name of the resource to load.
        """
        allowed, result = check_skill_allowed(skill_name)
        if not allowed:
            return f"Error: {result}"

        # Get resource
        resource = frappe.db.get_value("AI Skill Resource", {"parent": skill_name, "resource_name": resource_name}, "resource_value")
        if not resource:
            return f"Error: Resource '{resource_name}' not found for skill '{skill_name}'."

        log_activation(skill_name, agent_name, instance)
        return resource

    return [
        ToolSpec(
            fn=load_skill,
            name="load_skill",
            description="Load the full instructions body of a published AI Skill.",
            parameters={
                "skill_name": {
                    "type": "string",
                    "description": "The exact name of the skill from the index."
                }
            },
            required=["skill_name"]
        ),
        ToolSpec(
            fn=unload_skill,
            name="unload_skill",
            description="Unload a previously loaded AI Skill, removing it from the next turn's prompt and tool pool.",
            parameters={
                "skill_name": {
                    "type": "string",
                    "description": "The exact name of the skill to unload."
                }
            },
            required=["skill_name"]
        ),
        ToolSpec(
            fn=load_skill_resource,
            name="load_skill_resource",
            description="Load a specific resource row attached to an AI Skill.",
            parameters={
                "skill_name": {
                    "type": "string",
                    "description": "The exact name of the skill."
                },
                "resource_name": {
                    "type": "string",
                    "description": "The name of the resource to load."
                }
            },
            required=["skill_name", "resource_name"]
        )
    ]
