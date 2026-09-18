# Print Formats

## Overview

Print Formats define the PDF/HTML layout for printing documents. They can be created as Jinja templates (standard) or as HTML/CSS.

## File Structure

Standard Print Formats are stored alongside the DocType or as standalone files:

```
{app_name}/{app_name}/{module_name}/print_format/{print_format_name}/
├── {print_format_name}.json    # Print Format metadata
└── {print_format_name}.html    # Jinja template (for Standard type)
```

## Print Format Types

| Type         | Storage             | Use Case                               |
| ------------ | ------------------- | -------------------------------------- |
| **Standard** | `.html` file in app | Version-controlled, part of the app    |
| **Custom**   | Stored in DB        | Created via UI, per-site customization |

## Creating a Standard Print Format

### 1. Metadata JSON

```json
{
  "doctype": "Print Format",
  "name": "Custom Invoice",
  "doc_type": "Sales Invoice",
  "module": "My Module",
  "standard": "Yes",
  "print_format_type": "Jinja",
  "default_print_language": "en"
}
```

### 2. Jinja Template

```html
{# {app_name}/{module}/print_format/custom_invoice/custom_invoice.html #}

<div class="print-format">
  <div style="text-align: center;">
    <h2>{{ doc.company }}</h2>
    <p>{{ doc.name }}</p>
  </div>

  <table class="table table-bordered">
    <thead>
      <tr>
        <th>Item</th>
        <th>Qty</th>
        <th>Rate</th>
        <th>Amount</th>
      </tr>
    </thead>
    <tbody>
      {% for item in doc.items %}
      <tr>
        <td>{{ item.item_name }}</td>
        <td>{{ item.qty }}</td>
        <td>{{ frappe.format_value(item.rate, {"fieldtype": "Currency"}) }}</td>
        <td>
          {{ frappe.format_value(item.amount, {"fieldtype": "Currency"}) }}
        </td>
      </tr>
      {% endfor %}
    </tbody>
  </table>

  <div style="text-align: right;">
    <p>
      <strong
        >Grand Total: {{ frappe.format_value(doc.grand_total, {"fieldtype":
        "Currency"}) }}</strong
      >
    </p>
  </div>
</div>
```

### Available Template Variables

| Variable                           | Description                            |
| ---------------------------------- | -------------------------------------- |
| `doc`                              | The document being printed             |
| `frappe`                           | Frappe module (utilities, DB access)   |
| `frappe.format_value(value, meta)` | Format value based on fieldtype        |
| `frappe.format_date(date)`         | Format date per user settings          |
| `nowdate()`                        | Current date                           |
| `doc.get_formatted(fieldname)`     | Get field value with proper formatting |
| `frappe.get_print_style()`         | Get the print CSS                      |

### Letter Head

Print Formats automatically include the company's Letter Head if configured. Access via `{{ letter_head }}` in the template.

## Creating Programmatically

```python
import frappe

frappe.get_doc({
	"doctype": "Print Format",
	"name": "Custom Invoice",
	"doc_type": "Sales Invoice",
	"module": "My Module",
	"standard": "No",
	"print_format_type": "Jinja",
	"html": """<div class="print-format">{{ doc.name }}</div>""",
}).insert(ignore_permissions=True)
```

## PDF Generation Hooks

Override the global PDF header, body wrapper, or footer via `hooks.py`. These affect **all** PDF output (not per-print-format):

```python
# hooks.py
pdf_header_html = "myapp.utils.pdf.custom_pdf_header"
pdf_body_html = "myapp.utils.pdf.custom_pdf_body"
pdf_footer_html = "myapp.utils.pdf.custom_pdf_footer"
```

```python
# myapp/utils/pdf.py

def custom_pdf_header(html, options):
	"""Return custom HTML for PDF header"""
	return '<div style="text-align: center; font-size: 10px;">My Company</div>'

def custom_pdf_body(html, options):
	"""Wrap the print format body HTML"""
	return f'<div class="custom-pdf-wrapper">{html}</div>'

def custom_pdf_footer(html, options):
	"""Return custom HTML for PDF footer"""
	return '<div style="text-align: center; font-size: 8px;">Page {page} of {topage}</div>'
```