# Project Setup

Step-by-step instructions for setting up a Frappe + Vue.js SPA frontend.

## Step 1: Create `vite.config.js`

The `frappeui()` Vite plugin handles build output, API proxying, and boot data injection:

```javascript
import vue from "@vitejs/plugin-vue";
import frappeui from "frappe-ui/vite";
import path from "path";
import { defineConfig } from "vite";

export default defineConfig({
	plugins: [
		frappeui({
			frappeProxy: true,           // Proxy /api/ requests to Frappe during vite dev
			lucideIcons: true,           // Auto-import Lucide icons as Vue components
			jinjaBootData: true,         // Inject Frappe boot data (user, translations) into window
			buildConfig: {
				outDir: `../{app_name}/public/{frontend_dir}`,     // Built assets go here
				emptyOutDir: true,
				indexHtmlPath: `../{app_name}/www/{app_route}/index.html`,  // Jinja entry point
			},
			frappeTypes: {               // Optional: auto-generate TS types from DocType schemas
				input: {
					{app_name}: ["my_doctype_1", "my_doctype_2"],
				},
			},
		}),
		vue(),
	],
	resolve: {
		alias: {
			"@": path.resolve(__dirname, "src"),
		},
	},
});
```

### `frappeui()` Plugin Options

| Option                      | Type     | Purpose                                                                       |
| --------------------------- | -------- | ----------------------------------------------------------------------------- |
| `frappeProxy`               | `bool`   | Proxies `/api/` requests to the Frappe dev server during `vite dev`           |
| `jinjaBootData`             | `bool`   | Injects `__('...')` translations and user context into the page at build time |
| `lucideIcons`               | `bool`   | Auto-imports Lucide icons as Vue components (`~icons/lucide/icon-name`)       |
| `buildConfig.outDir`        | `string` | Where built assets go — must be inside app's `public/` directory              |
| `buildConfig.emptyOutDir`   | `bool`   | Clear output directory before each build                                      |
| `buildConfig.indexHtmlPath` | `string` | Where the Jinja entry HTML is placed for Frappe to serve                      |
| `frappeTypes.input`         | `object` | Map of `{app_name: [doctype_slugs]}` to auto-generate TypeScript interfaces   |

---

## Step 2: Create `package.json`

Core dependencies for a Vue frontend:

```json
{
  "name": "{app_name}-ui",
  "private": true,
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "vite build"
  },
  "dependencies": {
    "@vitejs/plugin-vue": "^4.2.3",
    "@vueuse/core": "^10.0.2",
    "dayjs": "^1.11.7",
    "frappe-ui": "0.1.192",
    "pinia": "^2.0.33",
    "socket.io-client": "^4.7.2",
    "vue": "^3.5.14",
    "vue-router": "^4.2.2"
  },
  "devDependencies": {
    "autoprefixer": "^10.4.13",
    "postcss": "^8.4.5",
    "tailwindcss": "^3.4.15",
    "vite": "^4.4.9"
  }
}
```

> **Always use the same `frappe-ui` version as the helpdesk app** to ensure compatibility. Check `apps/helpdesk/desk/package.json` for the current pinned version.

---

## Step 3: Create `tailwind.config.js` and `postcss.config.js`

```javascript
// tailwind.config.js
const plugin = require("tailwindcss/plugin");

module.exports = {
  presets: [require("frappe-ui/src/utils/tailwind.config")],
  content: [
    "./index.html",
    "./src/**/*.{vue,js,ts,jsx,tsx}",
    "./node_modules/frappe-ui/src/components/**/*.{vue,js,ts}",
  ],
  theme: {
    extend: {},
  },
  plugins: [],
};
```

```javascript
// postcss.config.js
module.exports = {
  plugins: {
    tailwindcss: {},
    autoprefixer: {},
  },
};
```

---

## Step 4: Create `src/index.css`

```css
@tailwind base;
@tailwind components;
@tailwind utilities;
```

---

## Step 5: Create `src/main.js`

```javascript
import { createApp } from "vue";
import {
  Button,
  Dialog,
  ErrorMessage,
  FormControl,
  frappeRequest,
  FrappeUI,
  setConfig,
  TextInput,
  toast,
  Tooltip,
} from "frappe-ui";
import { createPinia } from "pinia";
import App from "./App.vue";
import { router } from "./router";
import "./index.css";

// Configure frappe-ui to use Frappe's request handler
setConfig("resourceFetcher", frappeRequest);

// Handle server messages
setConfig("fallbackErrorHandler", (error) => {
  const msg = error.exc_type
    ? (error.messages || error.message || []).join(", ")
    : error.message;
  toast.error(msg);
});

// Global components (available without importing)
const globalComponents = {
  Button,
  Dialog,
  ErrorMessage,
  FormControl,
  TextInput,
  Tooltip,
};

const pinia = createPinia();
const app = createApp(App);

app.use(FrappeUI);
app.use(pinia);
app.use(router);

for (const c in globalComponents) {
  app.component(c, globalComponents[c]);
}

if (import.meta.env.DEV) {
  // In dev mode, fetch boot data via API since Jinja doesn't render
  frappeRequest({
    url: "/api/method/{app_name}.www.{app_route}.index.get_context_for_dev",
  }).then((values) => {
    for (let key in values) {
      window[key] = values[key];
    }
    app.mount("#app");
  });
} else {
  app.mount("#app");
}
```

---

## Step 6: Create `src/App.vue`

```vue
<template>
  <router-view />
</template>

<script setup>
// Global app setup if needed
</script>
```

---

## Step 7: Create `src/router/index.ts`

```typescript
import { createRouter, createWebHistory } from "vue-router";

const routes = [
  {
    path: "/",
    name: "Home",
    redirect: "/dashboard",
  },
  {
    path: "/dashboard",
    name: "Dashboard",
    component: () => import("@/pages/Dashboard.vue"),
  },
  {
    path: "/records",
    name: "RecordList",
    component: () => import("@/pages/RecordList.vue"),
  },
  {
    path: "/records/:id",
    name: "RecordDetail",
    component: () => import("@/pages/RecordDetail.vue"),
    props: true,
  },
  {
    path: "/:pathMatch(.*)*",
    name: "NotFound",
    component: () => import("@/pages/NotFound.vue"),
  },
];

export const router = createRouter({
  history: createWebHistory("/{app_route}/"), // Must match the www route
  routes,
});

// Auth guard (optional)
router.beforeEach(async (to, _, next) => {
  // Check authentication state
  // Redirect to login if not authenticated
  next();
});
```

---

## Step 8: Configure `hooks.py`

```python
# hooks.py

# Route all sub-paths to the SPA entry point (Frappe serves the Jinja template)
website_route_rules = [
	{
		"from_route": "/{app_route}/<path:app_path>",
		"to_route": "{app_route}",
	},
]

# Add to the Frappe app launcher (the grid on /app)
add_to_apps_screen = [
	{
		"name": "{app_name}",
		"logo": "/assets/{app_name}/{frontend_dir}/favicon.svg",
		"title": "{App Title}",
		"route": "/{app_route}",
		"has_permission": "{app_name}.api.permission.has_permission",
	},
]
```