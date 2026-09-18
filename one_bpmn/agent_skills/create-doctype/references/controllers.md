# frappe-ui Component Reference

## General Backend API Calls

```vue
<template>
  <Button @click="todos.reload()" :loading="todos.loading"> Reload </Button>
  <pre>{{ todos }}</pre>
</template>

<script setup>
import { createResource } from "frappe-ui";
let todos = createResource({
  url: "/api/method/frappe.client.get_list",
  params: {
    doctype: "ToDo",
    filters: {
      allocated_to: "faris@frappe.io",
    },
  },
});
todos.fetch(); // GET request

// POST request
todos.submit({
  description: "New ToDo",
});
</script>
```

## Document Resource

```vue
<script setup>
let todo = createDocumentResource({
  doctype: "ToDo",
  name: "",
  whitelistedMethods: {
    sendEmail: "send_email",
  },
  onError(error) {},
  onSuccess(data) {},
  transform(doc) {
    doc.open = false;
    return doc;
  },
  delete: {
    onSuccess() {},
    onError() {},
  },
  setValue: {
    onSuccess() {},
    onError() {},
  },
});
</script>
```

### Document Resource API

```js
todo.doc; // doc returned from request
todo.reload(); // reload the doc
todo.update({ doctype: "", name: "" }); // update options

todo.get; // doc resource
todo.get.loading; // true when data is being fetched
todo.get.error; // error from request
todo.get.promise; // promise, can be awaited

todo.setValue; // resource to set value(s)
todo.setValue.submit({
  status: "Closed",
  description: "Updated description",
});

// Debounced version (runs once after 500ms)
todo.setValueDebounced.submit({ description: "Updated description" });

todo.delete; // resource to delete the document
todo.delete.submit();

// Whitelisted methods become resources
todo.sendEmail;
todo.sendEmail.submit;
todo.sendEmail.loading;
```

---

## List Resource (useList)

### Basic Usage

```vue
<template>
  <div class="space-y-4">
    <div
      class="flex items-center justify-between"
      v-for="todo in todos.data"
      :key="todo.name"
    >
      <div>{{ todo.description }}</div>
      <Badge>{{ todo.status }}</Badge>
    </div>
  </div>
  <Button @click="todos.next()"> Next Page </Button>
</template>
<script setup>
import { useList } from "frappe-ui";
let todos = useList({
  doctype: "ToDo",
  fields: ["name", "description", "status"],
  orderBy: "creation desc",
  start: 0,
  pageLength: 5,
});
todos.fetch();
</script>
```

### Options API

Register the `resourcesPlugin` first in `main.js`:

```js
import { resourcesPlugin } from "frappe-ui";
app.use(resourcesPlugin);
```

Then in `.vue` files:

```vue
<script>
export default {
  resources: {
    todos() {
      return {
        type: "list",
        doctype: "ToDo",
        fields: ["name", "description", "status"],
        orderBy: "creation desc",
        start: 0,
        pageLength: 5,
        auto: true,
      };
    },
  },
};
</script>
```

### useList Options

```js
let todos = useList({
  doctype: "ToDo",
  fields: ["name", "description", "status"],
  filters: { status: "Open" },
  orderBy: "creation desc",
  start: 0, // default: 0
  pageLength: 20, // default: 20
  parent: null, // parent doctype for child tables
  debug: 0,
  cacheKey: "todos", // or array: ['todos', 'faris@frappe.io']
  url: "todo_app.api.get_todos", // custom API (default: frappe.client.get_list)
  auto: true, // auto-fetch on creation

  // Events
  onError(error) {},
  onSuccess(data) {},
  transform(data) {
    for (let d of data) {
      d.open = false;
    }
    return data;
  },
  fetchOne: { onSuccess() {}, onError() {} },
  insert: { onSuccess() {}, onError() {} },
  delete: { onSuccess() {}, onError() {} },
  setValue: { onSuccess() {}, onError() {} },
  runDocMethod: { onSuccess() {}, onError() {} },
});
```

### useList API

```js
let todos = useList({...})

todos.data            // data returned from request
todos.originalData    // response before transform
todos.reload()        // reload existing list
todos.next()          // fetch next page
todos.hasNextPage     // whether there is next page

// Update options
todos.update({ fields: ['*'], filters: { status: 'Closed' } })

todos.loading         // true when fetching
todos.error           // request error
todos.promise         // awaitable promise

// Fetch and update a single record in the list
todos.fetchOne.submit(name)

// Set value(s) for a single record
todos.setValue.submit({ name: '', status: 'Closed', description: 'Updated' })

// Insert a new record
todos.insert.submit({ description: 'New todo' })

// Delete a single record
todos.delete.submit(name)

// Run a doc method
todos.runDocMethod.submit({ method: 'send_email', name: '', email: 'test@example.com' })
```

---

## ListView Component

### Column Definition

- `label` & `key` are required
- `width`: number (e.g., `3` = 3x default) or string (`"300px"`, `"12rem"`)
- `align`: `"start"` / `"center"` / `"end"` (or `"left"` / `"middle"` / `"right"`)
- Additional attributes can be used for custom header rendering

### Row Definition

- Must contain a unique key matching `row-key` prop
- Field values can be strings or objects with a `label` attribute for custom rendering:

```js
row: {
    name: { label: 'John Doe', image: '/johndoe.jpg' },
    age: 25,
    status: { label: 'Active', color: 'green' }
}
```

### Grouped Rows Format

```js
[
  {
    group: "Group Title",
    collapsed: false,
    rows: [
      { id: 1, key1: value1, key2: value2 },
      { id: 2, key1: value1, key2: value2 },
    ],
  },
];
```

### Options

- `getRowRoute: (row) => ({ name: 'User', params: { userId: row.id } })` — router-link routing
- `onRowClick: (row) => console.log(row)` — click handler
- `selectable` (Boolean, default: true) — show checkboxes
- `showTooltip` (Boolean, default: true) — hover tooltip
- `resizeColumn` (Boolean, default: false) — draggable column resize

### Selection Banner

```vue
<ListSelectBanner>
    <template #actions="{ unselectAll }">
      <div class="flex gap-2">
        <Button variant="ghost" label="Delete" />
        <Button variant="ghost" label="Unselect all" @click="unselectAll" />
      </div>
    </template>
</ListSelectBanner>
```

### Cell Slot

```vue
<ListView :columns="columns" :rows="rows" row-key="id">
    <template #cell="{ item, row, column }">
        <Badge v-if="column.key == 'status'">{{ item }}</Badge>
        <span v-else>{{ item }}</span>
    </template>
</ListView>
```

### Group Header Slot

```vue
<template #group-header="{ group }">
  <span class="text-base font-medium">
    {{ group.group }} ({{ group.rows.length }})
  </span>
</template>
```

---

## Toasts

```vue
<script setup>
import { toast } from "frappe-ui";

toast.success("Converted successfully");
toast.warning("Converted Pending");
toast.error("Conversion Failed");
</script>
```

---

## Badge Component

```vue
<Badge variant="solid" theme="green" size="md" label="Active">Active</Badge>
```

- **Variants:** `solid`, `subtle`, `outline`, `ghost`
- **Themes:** `gray`, `blue`, `green`, `orange`, `red`
- **Sizes:** `sm`, `md`, `lg`

---

## FormControl Component

```vue
<FormControl
  type="text"
  size="sm"
  variant="subtle"
  placeholder="Enter text"
  label="Label"
  v-model="value"
/>
```

- **Input types:** `text`, `number`, `email`, `date`, `password`, `search`, `textarea`
- **Other types:** `select` (with `:options`), `autocomplete` (with `:options`), `checkbox`
- **Variants:** `subtle`, `outline`
- **Sizes:** `sm`, `md`, `lg`, `xl`

### Prefix/Suffix Slots

```vue
<FormControl type="text" label="Search">
    <template #prefix>
        <FeatherIcon class="w-4" name="search" />
    </template>
</FormControl>
```

---

## Dropdown Component

Icons use lucide icon names.

```vue
<Dropdown :options="actions" />
<!-- Or with custom trigger -->
<Dropdown :options="actions">
    <Button variant="solid">Custom Trigger</Button>
</Dropdown>
```

### Options Format

```js
// Simple list
const actions = [
  { label: "Edit", icon: "edit", onClick: () => {} },
  { label: "Delete", icon: "trash-2", theme: "red", onClick: () => {} },
];

// Grouped
const groupedActions = [
  {
    group: "Actions",
    items: [
      { label: "Edit", icon: "edit", onClick: () => {} },
      { label: "Duplicate", icon: "copy", onClick: () => {} },
    ],
  },
];

// With submenus
const submenuActions = [
  {
    label: "New",
    icon: "plus",
    submenu: [
      { label: "New Document", icon: "file-plus", onClick: () => {} },
      { label: "New Template", icon: "file-text", onClick: () => {} },
    ],
  },
];
```

**Placement:** `"left"` (default), `"right"`, `"center"`

---

## Dialog Component

### Basic with Actions

```vue
<Dialog
  :options="{
    title: 'Confirm Action',
    message: 'Are you sure?',
    size: 'lg',
    icon: { name: 'alert-triangle', appearance: 'warning' },
    actions: [{ label: 'Confirm', variant: 'solid', onClick: () => {} }],
  }"
  v-model="showDialog"
/>
```

### Custom Content with Slots

```vue
<Dialog v-model="showDialog">
    <template #body-title>
        <h3 class="text-2xl font-semibold">Custom Title</h3>
    </template>
    <template #body-content>
        <div class="space-y-4">
            <p>Custom content here.</p>
        </div>
    </template>
    <template #actions="{ close }">
        <div class="flex gap-2">
            <Button variant="solid" @click="close">Save</Button>
            <Button variant="outline" @click="close">Cancel</Button>
        </div>
    </template>
</Dialog>
```

### Sizes

`"sm"`, `"lg"`, `"4xl"`

### Props

- `:disable-outside-click-to-close="true"` — prevent closing on outside click

### With Interactive Components

Dropdowns and Autocomplete work inside dialogs with proper z-index layering:

```vue
<Dialog v-model="showDialog">
    <template #body-content>
        <Autocomplete :options="options" v-model="value" />
        <Dropdown :options="dropdownOptions">
            <Button variant="outline">{{ selectedOption }}</Button>
        </Dropdown>
    </template>
</Dialog>
```