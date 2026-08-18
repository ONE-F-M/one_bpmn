import frappe
from one_bpmn.agents.llm_provider.base import ToolSpec
from frappe.utils import now_datetime
import hashlib

def log_activation(skill_name, agent_name, instance=None):
    if not instance:
        return
        
    conversation = None
    if instance.context_doctype == "Chat Conversation":
        conversation = instance.context_docname
        
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
            "loaded_at": now_datetime()
        }).insert(ignore_permissions=True)
        frappe.db.commit()
    except Exception as e:
        frappe.log_error(f"Failed to log AI Skill Activation: {e}")

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
        
        log_activation(skill_name, agent_name, instance)
        
        # In a real BPMN process context we don't have get_data/set_data on the instance
        # Instead, we are inside a tool call. If we need to pass data back, we just return it.
        # But this was supposed to inject it into active_skills for the dynamic preamble on the NEXT loop.
        # SpiffWorkflow holds data on the task instance. This might not be accessible from here.
        # As a hack, we can write it to Frappe cache to be picked up by the dispatcher
        cache_key = f"active_skills_{instance.name}" if instance else None
        if cache_key:
            active = frappe.cache().get_value(cache_key) or []
            if result.body not in active:
                active.append(result.body)
                frappe.cache().set_value(cache_key, active, expires_in_sec=86400)
                
            # Also track the skill names!
            names_key = f"active_skill_names_{instance.name}"
            active_names = frappe.cache().get_value(names_key) or []
            if skill_name not in active_names:
                active_names.append(skill_name)
                frappe.cache().set_value(names_key, active_names, expires_in_sec=86400)
                
        return result.body
        
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
