import frappe
from frappe import _

@frappe.whitelist()
def get_skills_library():
    """
    Returns the list of AI Skills for the Skills Manager UI.
    """
    skills = frappe.get_all(
        "AI Skill",
        fields=["name", "skill_name", "status", "tier", "description", "owner_team", "token_estimate"],
        order_by="modified desc"
    )
    return skills

@frappe.whitelist()
def update_skill_body(skill_name: str, new_body: str):
    """
    Updates the body of a skill.
    """
    frappe.only_for("System Manager", "Process Owner")
    
    skill = frappe.get_doc("AI Skill", skill_name)
    skill.body = new_body
    skill.save(ignore_permissions=True)
    return "Success"

@frappe.whitelist()
def get_skill_telemetry(skill_name: str):
    """
    Fetches the activation logs for a given skill.
    """
    activations = frappe.get_all(
        "AI Skill Activation",
        filters={"skill": skill_name},
        fields=["name", "agent_run", "conversation", "loaded_at"],
        order_by="loaded_at desc",
        limit=50
    )
    return activations
