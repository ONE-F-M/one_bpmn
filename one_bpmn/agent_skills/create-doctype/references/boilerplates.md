# frappe-ui API & State Management

## Calling Frappe APIs from Vue

### `createResource` — Generic API Calls

```javascript
import { createResource } from "frappe-ui";

// Fetch a list of records
const records = createResource({
  url: "frappe.client.get_list",
  params: {
    doctype: "My DocType",
    fields: ["name", "title", "status"],
    filters: { status: "Active" },
    limit_page_length: 20,
  },
  auto: true, // Fetch immediately on creation
});

// Access data reactively in template
// records.data, records.loading, records.error
```

### `createDocumentResource` — CRUD Operations

```javascript
import { createDocumentResource } from "frappe-ui";

// Load a specific document
const doc = createDocumentResource({
  doctype: "My DocType",
  name: "DOC-001",
  auto: true,
});

// Reactive access
doc.doc; // Document data (reactive)
doc.doc.title; // Specific field

// Operations
doc.save(); // Save changes
doc.delete(); // Delete document
doc.reload(); // Refresh from server

// Update a field
doc.setValue.submit({ field: "status", value: "Closed" });
```

### `createListResource` — Paginated Lists

```javascript
import { createListResource } from "frappe-ui";

const list = createListResource({
  doctype: "My DocType",
  fields: ["name", "title", "status", "creation"],
  filters: { status: "Open" },
  orderBy: "creation desc",
  pageLength: 20,
  auto: true,
});

// Paginate
list.next(); // Load next page
list.previous(); // Load previous page
list.reload(); // Refresh current page
```

### Direct API Calls

```javascript
import { call } from "frappe-ui";

// Call a whitelisted method
const result = await call("myapp.api.process_data", {
  record_name: "DOC-001",
});
```

---

## Pinia Store Pattern

```typescript
// src/stores/auth.ts
import { defineStore } from "pinia";
import { call } from "frappe-ui";

export const useAuthStore = defineStore("auth", {
  state: () => ({
    user: null as any,
    isLoggedIn: false,
  }),

  actions: {
    async init() {
      const data = await call("frappe.auth.get_logged_user");
      this.user = data;
      this.isLoggedIn = !!data;
    },
  },
});
```

---

## Socket.io Integration

```typescript
// src/socket.ts
import { io } from "socket.io-client";

export function initSocket() {
  const host = window.location.hostname;
  const port = window.location.port
    ? `:${import.meta.env.VITE_SOCKET_PORT || 9000}`
    : "";
  const protocol = port ? "http" : "https";
  const url = `${protocol}://${host}${port}`;

  const socket = io(url, {
    withCredentials: true,
    reconnectionAttempts: 5,
  });

  return socket;
}
```