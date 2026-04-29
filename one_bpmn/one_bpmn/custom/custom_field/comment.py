def get_comment_custom_fields():
    return {
        "Comment": [
            {
                "fieldname": "is_processa_comment",
                "fieldtype": "Check",
                "insert_after": "reference_name",
                "read_only":1,
                "label": "Is Processa Comment",
                "default": "0",
            },
            {
                "fieldname": "custom_element_id",
                "fieldtype": "Data",
                "insert_after": "reference_name",
                "label": "Element ID",
            },
            {
                "fieldname": "custom_is_task",
                "fieldtype": "Check",
                "insert_after": "custom_element_id",
                "label": "Is Task",
                "default": "0",
            },
            {
                "fieldname": "custom_status",
                "fieldtype": "Select",
                "insert_after": "custom_is_task",
                "label": "Status",
                "options": "\nOpen\nResolved\nClosed",
                "default": "Open",
            },
            {
                "fieldname": "custom_assigned_to",
                "fieldtype": "Link",
                "insert_after": "custom_status",
                "label": "Assigned To",
                "options": "User",
            },
        ]
    }
