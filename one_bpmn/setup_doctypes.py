import frappe

def create_ai_skill_doctypes():
    # 1. AI Skill Resource (Child Table)
    if not frappe.db.exists("DocType", "AI Skill Resource"):
        frappe.get_doc({
            "doctype": "DocType",
            "name": "AI Skill Resource",
            "module": "ONE BPMN",
            "custom": 0,
            "istable": 1,
            "fields": [
                {
                    "fieldname": "resource_type",
                    "fieldtype": "Select",
                    "label": "Resource Type",
                    "options": "Script\nReference\nAsset",
                    "reqd": 1,
                    "in_list_view": 1
                },
                {
                    "fieldname": "resource_name",
                    "fieldtype": "Data",
                    "label": "Resource Name",
                    "reqd": 1,
                    "in_list_view": 1
                },
                {
                    "fieldname": "resource_value",
                    "fieldtype": "Text",
                    "label": "Resource Value",
                    "reqd": 1
                }
            ]
        }).insert()
        print("Created AI Skill Resource")

    # 2. AI Skill Allowed Tool (Child Table)
    if not frappe.db.exists("DocType", "AI Skill Allowed Tool"):
        frappe.get_doc({
            "doctype": "DocType",
            "name": "AI Skill Allowed Tool",
            "module": "ONE BPMN",
            "custom": 0,
            "istable": 1,
            "fields": [
                {
                    "fieldname": "tool",
                    "fieldtype": "Data",
                    "label": "Tool",
                    "reqd": 1,
                    "in_list_view": 1
                }
            ]
        }).insert()
        print("Created AI Skill Allowed Tool")

    # 3. AI Skill
    if not frappe.db.exists("DocType", "AI Skill"):
        frappe.get_doc({
            "doctype": "DocType",
            "name": "AI Skill",
            "module": "ONE BPMN",
            "custom": 0,
            "autoname": "field:skill_name",
            "fields": [
                {
                    "fieldname": "skill_name",
                    "fieldtype": "Data",
                    "label": "Skill Name",
                    "unique": 1,
                    "reqd": 1
                },
                {
                    "fieldname": "status",
                    "fieldtype": "Select",
                    "label": "Status",
                    "options": "Draft\nActive\nDeprecated",
                    "default": "Draft",
                    "reqd": 1
                },
                {
                    "fieldname": "tier",
                    "fieldtype": "Select",
                    "label": "Tier",
                    "options": "Draft-Only\nRead-Only\nAction-Allowed"
                },
                {
                    "fieldname": "owner_team",
                    "fieldtype": "Data",
                    "label": "Owner Team"
                },
                {
                    "fieldname": "description",
                    "fieldtype": "Small Text",
                    "label": "Description",
                    "reqd": 1
                },
                {
                    "fieldname": "body",
                    "fieldtype": "Markdown Editor",
                    "label": "Body",
                    "reqd": 1
                },
                {
                    "fieldname": "token_estimate",
                    "fieldtype": "Int",
                    "label": "Token Estimate",
                    "read_only": 1
                },
                {
                    "fieldname": "resources",
                    "fieldtype": "Table",
                    "label": "Resources",
                    "options": "AI Skill Resource"
                },
                {
                    "fieldname": "allowed_tools",
                    "fieldtype": "Table",
                    "label": "Allowed Tools",
                    "options": "AI Skill Allowed Tool"
                }
            ]
        }).insert()
        print("Created AI Skill")
    frappe.db.commit()

if __name__ == "__main__":
    frappe.init(site="onefm.localhost")
    frappe.connect()
    create_ai_skill_doctypes()
    frappe.destroy()
