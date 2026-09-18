# Web Forms

## Overview

Web Forms create public-facing forms for data collection. They map to a DocType and allow portal users or anonymous visitors to create/edit documents.

## File Structure

```
{app_name}/{app_name}/{module_name}/web_form/{web_form_name}/
├── {web_form_name}.json    # Web Form definition
├── {web_form_name}.js      # Client-side logic (optional)
└── {web_form_name}.py      # Server-side logic (optional)
```

## Web Form JSON

```json
{
  "doctype": "Web Form",
  "name": "contact-us",
  "title": "Contact Us",
  "doc_type": "Issue",
  "module": "My Module",
  "route": "contact-us",
  "published": 1,
  "allow_edit": 0,
  "allow_delete": 0,
  "allow_multiple": 1,
  "login_required": 0,
  "show_sidebar": 0,
  "show_attachments": 0,
  "success_url": "/thank-you",
  "success_message": "Thank you for contacting us!",
  "introduction_text": "Please fill out the form below.",
  "web_form_fields": [
    {
      "fieldname": "subject",
      "fieldtype": "Data",
      "label": "Subject",
      "reqd": 1
    },
    {
      "fieldname": "raised_by",
      "fieldtype": "Data",
      "label": "Your Email",
      "reqd": 1,
      "options": "Email"
    },
    {
      "fieldname": "description",
      "fieldtype": "Text Editor",
      "label": "Description",
      "reqd": 1
    }
  ]
}
```

## Key Properties

| Property            | Description                                    |
| ------------------- | ---------------------------------------------- |
| `doc_type`          | Target DocType where submissions are saved     |
| `route`             | URL path (e.g., `/contact-us`)                 |
| `published`         | `1` to make publicly accessible                |
| `login_required`    | `1` to require login, `0` for anonymous access |
| `allow_edit`        | `1` to let users edit their submissions        |
| `allow_delete`      | `1` to let users delete their submissions      |
| `allow_multiple`    | `1` to allow multiple submissions per user     |
| `success_url`       | Redirect URL after submission                  |
| `success_message`   | Message shown after submission                 |
| `introduction_text` | Text displayed above the form                  |
| `show_sidebar`      | `1` to show portal sidebar                     |
| `show_attachments`  | `1` to allow file attachments                  |
| `is_standard`       | `1` for app-bundled forms (version controlled) |

## Client-Side Logic

```javascript
// {app_name}/{module}/web_form/{web_form_name}/{web_form_name}.js
frappe.ready(function () {
  frappe.web_form.after_load = function () {
    // Runs after form loads
  };

  frappe.web_form.validate = function () {
    // Return false to prevent submission
    let email = frappe.web_form.get_value("raised_by");
    if (!email || !email.includes("@")) {
      frappe.msgprint("Please enter a valid email");
      return false;
    }
    return true;
  };

  frappe.web_form.after_save = function () {
    // Runs after successful submission
  };
});
```

## Server-Side Logic

```python
# {app_name}/{module}/web_form/{web_form_name}/{web_form_name}.py
import frappe


def get_context(context):
	"""Modify template context before rendering"""
	context.custom_data = frappe.get_all("FAQ", fields=["question", "answer"], limit=5)
```