# Workspaces

## Overview

Workspaces are module landing pages in Frappe's sidebar navigation. They contain shortcuts, link cards, dashboard charts, number cards, quick lists, and custom HTML blocks.

## Workspace JSON File

Workspaces are defined as JSON files in your app's module directory:

```
{app_name}/{app_name}/{module_name}/workspace/{workspace_name}/{workspace_name}.json
```

## Components (6 Types)

### 1. Shortcuts

Quick-access tiles that can link to DocTypes, Reports, Pages, Dashboards, or URLs.

```json
{
  "shortcuts": [
    {
      "type": "DocType",
      "link_to": "Task",
      "label": "Task",
      "doc_view": "List",
      "stats_filter": "{\"status\": \"Open\"}",
      "format": "{} Open",
      "color": "#ed8c2b"
    },
    {
      "type": "Report",
      "link_to": "Daily Timesheet Summary",
      "label": "Timesheet Summary"
    },
    {
      "type": "URL",
      "url": "https://example.com",
      "label": "External Link"
    }
  ]
}
```

**Shortcut `doc_view` options:** `List`, `Report Builder`, `Dashboard`, `Tree`, `New`, `Calendar`, `Kanban`

### 2. Link Cards

Organized groups of links with card headers:

```json
{
  "links": [
    {
      "type": "Card Break",
      "label": "Masters",
      "icon": "project"
    },
    {
      "type": "Link",
      "label": "Project",
      "link_type": "DocType",
      "link_to": "Project"
    },
    {
      "type": "Link",
      "label": "Task",
      "link_type": "DocType",
      "link_to": "Task"
    },
    {
      "type": "Card Break",
      "label": "Reports"
    },
    {
      "type": "Link",
      "label": "Project Summary",
      "link_type": "Report",
      "link_to": "Project Summary",
      "is_query_report": 1
    }
  ]
}
```

### 3. Dashboard Charts

Embed existing `Dashboard Chart` records:

```json
{
  "charts": [
    {
      "chart_name": "Open Tasks",
      "label": "Open Tasks"
    }
  ]
}
```

> **Prerequisite:** Create the `Dashboard Chart` DocType record first, then reference it by name.

### 4. Number Cards

Embed existing `Number Card` records:

```json
{
  "number_cards": [
    {
      "number_card_name": "Total Open Tasks",
      "label": "Open Tasks"
    }
  ]
}
```

> **Prerequisite:** Create the `Number Card` DocType record first, then reference it by name.

### 5. Quick Lists

Embedded filtered list views:

```json
{
  "quick_lists": [
    {
      "document_type": "Task",
      "label": "My Open Tasks",
      "quick_list_filter": "[\"Task\", \"_assign\", \"like\", \"%{{ frappe.session.user }}%\"]"
    }
  ]
}
```

### 6. Custom Blocks

Arbitrary HTML content via `Custom HTML Block` DocType:

```json
{
  "custom_blocks": [
    {
      "custom_block_name": "Welcome Banner",
      "label": "Welcome"
    }
  ]
}
```

## Workspace Properties

| Property             | Description                                                  |
| -------------------- | ------------------------------------------------------------ |
| `label`              | Workspace name (unique, used as `name`)                      |
| `title`              | Display title                                                |
| `module`             | Link to Module Def                                           |
| `icon`               | Sidebar icon                                                 |
| `indicator_color`    | Icon color: `green`, `blue`, `orange`, `red`, `purple`, etc. |
| `parent_page`        | Parent workspace for nesting                                 |
| `public`             | `1` for all users, `0` for private                           |
| `roles`              | Restrict visibility by role (Has Role child table)           |
| `restrict_to_domain` | Only show for specific Domain                                |
| `sequence_id`        | Sidebar sort order                                           |
| `is_hidden`          | `1` to hide from sidebar                                     |

## Creating Dashboard Charts and Number Cards

### Dashboard Chart

```python
frappe.get_doc({
	"doctype": "Dashboard Chart",
	"chart_name": "Open Tasks by Priority",
	"chart_type": "Count",
	"document_type": "Task",
	"based_on": "creation",
	"filters_json": '{"status": "Open"}',
	"group_by_type": "Count",
	"group_by_based_on": "priority",
	"type": "Bar",
	"timespan": "Last Year",
	"time_interval": "Monthly",
}).insert(ignore_permissions=True)
```

### Number Card

```python
frappe.get_doc({
	"doctype": "Number Card",
	"name": "Total Open Tasks",
	"label": "Open Tasks",
	"document_type": "Task",
	"function": "Count",
	"filters_json": '{"status": "Open"}',
	"is_public": 1,
	"show_percentage_stats": 1,
	"stats_time_interval": "Weekly",
}).insert(ignore_permissions=True)
```