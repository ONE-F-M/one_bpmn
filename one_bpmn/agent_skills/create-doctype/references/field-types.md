# Field Types Reference

## Text / Data Fields

| Fieldtype         | Options / Notes                                                     |
| ----------------- | ------------------------------------------------------------------- |
| `Data`            | `length` (varchar length, default 140)                              |
| `Small Text`      | Short text (no rich formatting)                                     |
| `Text`            | Medium text                                                         |
| `Long Text`       | Large text                                                          |
| `Text Editor`     | Rich text HTML editor                                               |
| `Markdown Editor` | Markdown with preview                                               |
| `HTML Editor`     | Raw HTML editor                                                     |
| `Code`            | `options` = language (`Python`, `JavaScript`, `JSON`, `HTML`, etc.) |
| `Password`        | Encrypted, stored in `__Auth` table                                 |
| `Phone`           | Phone number input                                                  |
| `JSON`            | JSON data with editor                                               |
| `Read Only`       | Display-only computed text                                          |

## Number Fields

| Fieldtype  | Options / Notes                                         |
| ---------- | ------------------------------------------------------- |
| `Int`      | Integer                                                 |
| `Float`    | Decimal number                                          |
| `Currency` | `options` = currency field or static code (e.g., `USD`) |
| `Percent`  | 0–100 percentage                                        |
| `Rating`   | Star rating (0–1 float)                                 |
| `Duration` | Time duration                                           |

## Date / Time Fields

| Fieldtype  | Options / Notes    |
| ---------- | ------------------ |
| `Date`     | Date picker        |
| `Datetime` | Date + time picker |
| `Time`     | Time picker        |

## Link / Relationship Fields

| Fieldtype           | Options / Notes                                                      |
| ------------------- | -------------------------------------------------------------------- |
| `Link`              | `options` = target DocType name                                      |
| `Dynamic Link`      | `options` = fieldname of the controlling Link/Select field           |
| `Table`             | `options` = child DocType name                                       |
| `Table MultiSelect` | `options` = Link child DocType (child must have a single Link field) |

## Selection Fields

| Fieldtype      | Options / Notes                      |
| -------------- | ------------------------------------ |
| `Select`       | `options` = newline-separated values |
| `Autocomplete` | Free text with suggestions           |
| `Check`        | Boolean 0/1                          |
| `Color`        | Color picker (hex value)             |
| `Icon`         | Icon selector                        |

## Media / File Fields

| Fieldtype      | Options / Notes                                              |
| -------------- | ------------------------------------------------------------ |
| `Attach`       | File attachment (any type)                                   |
| `Attach Image` | Image-only attachment (with preview)                         |
| `Image`        | Display-only image (uses `options` = Attach Image fieldname) |
| `Signature`    | Signature pad                                                |
| `Barcode`      | Barcode display                                              |
| `Geolocation`  | Map with coordinates                                         |

## Layout Fields

| Fieldtype       | Options / Notes                                            |
| --------------- | ---------------------------------------------------------- |
| `Section Break` | Horizontal section divider (`collapsible` = 1 to collapse) |
| `Column Break`  | Column layout divider                                      |
| `Tab Break`     | Tab navigation divider                                     |
| `Fold`          | Hide everything below until expanded                       |
| `Heading`       | Display heading text                                       |

## Other Fields

| Fieldtype | Options / Notes                       |
| --------- | ------------------------------------- |
| `HTML`    | Display-only HTML content             |
| `Button`  | Action button (triggers client event) |

---

## Field Properties

| Property               | Purpose                                                    |
| ---------------------- | ---------------------------------------------------------- |
| `reqd`                 | Mandatory field                                            |
| `unique`               | Unique constraint                                          |
| `default`              | Default value                                              |
| `read_only`            | Not editable                                               |
| `hidden`               | Not visible                                                |
| `in_list_view`         | Show in list view                                          |
| `in_standard_filter`   | Show in sidebar filter                                     |
| `in_global_search`     | Include in global search                                   |
| `bold`                 | Bold in list view                                          |
| `depends_on`           | Visibility condition (e.g., `eval:doc.status == "Active"`) |
| `mandatory_depends_on` | Conditional mandatory                                      |
| `read_only_depends_on` | Conditional read-only                                      |
| `fetch_from`           | Auto-fetch from linked doc (e.g., `project.company`)       |
| `fetch_if_empty`       | Only fetch if field is empty                               |
| `options`              | Depends on fieldtype (see above)                           |
| `description`          | Help text below field                                      |
| `allow_in_quick_entry` | Show in quick entry dialog                                 |
| `translatable`         | Mark as translatable                                       |
| `no_copy`              | Don't copy when duplicating                                |
| `print_hide`           | Hide in print formats                                      |
| `report_hide`          | Hide in reports                                            |
| `search_index`         | Add database index                                         |
| `collapsible`          | For Section Break — start collapsed                        |