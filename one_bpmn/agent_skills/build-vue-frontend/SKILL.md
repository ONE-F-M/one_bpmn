---
name: "build-vue-frontend"
description: "Build a standalone Vue.js SPA frontend integrated with Frappe \u2014 uses frappe-ui, Vite, Vue 3, Pinia, TailwindCSS, vue-router, and website_route_rules for SPA routing. Use this skill when building or changing a Vue single page application inside Frappe, including frappe-ui components, Vite, Pinia and routing. Do NOT use it for desk JavaScript."
---

# Build Vue.js Frontend

Use this skill when you need to build a standalone Vue.js single-page application (SPA) that integrates with Frappe as a backend. This follows the established Frappe + Vue pattern using `frappe-ui` components and the `website_route_rules` hook for SPA routing.

> For Frappe desk form/list scripts (not standalone SPAs), see the `write-client-script` skill.

---

## Detailed References

| Reference                                                  | What's Inside                                                                                                                  |
| ---------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------ |
| [Project Setup](references/project-setup.md)               | Step-by-step: vite.config.js, package.json, Tailwind, main.js, App.vue, router, hooks.py (8 steps)                             |
| [frappe-ui API & State](references/frappe-ui-api.md)       | `createResource`, `createDocumentResource`, `createListResource`, direct API calls, Pinia store pattern, socket.io integration |
| [frappe-ui Components](references/frappe-ui-components.md) | ListView, Badge, FormControl, Dropdown, Dialog, Toasts — props, slots, options, and usage patterns                             |

---

## Architecture Overview

```
{app_name}/
├── {frontend_dir}/                    # Vue.js SPA source (e.g., "desk", "frontend")
│   ├── index.html                     # Entry point HTML
│   ├── package.json
│   ├── vite.config.js
│   ├── tailwind.config.js
│   ├── postcss.config.js
│   └── src/
│       ├── App.vue                    # Root component
│       ├── main.js                    # App bootstrap
│       ├── index.css                  # Global styles (Tailwind directives)
│       ├── router/
│       │   └── index.ts               # Vue Router config
│       ├── pages/                     # Route-based page components
│       ├── components/                # Reusable components
│       ├── composables/               # Vue composables (shared logic)
│       ├── stores/                    # Pinia stores (state management)
│       ├── types/                     # TypeScript types
│       └── utils.ts                   # Utility functions
├── {app_name}/
│   ├── public/{frontend_dir}/         # Built output (assets served by Frappe)
│   └── www/{app_route}/
│       └── index.html                 # Jinja template that boots the SPA
└── hooks.py                           # website_route_rules for SPA routing
```

---

## Development Workflow

```bash
# Install frontend dependencies
cd apps/{app_name}/{frontend_dir}
yarn install

# Run Vite dev server (auto-proxies to Frappe backend)
yarn dev
# → Visit http://localhost:8080/{app_route}

# Build for production (outputs to {app_name}/public/{frontend_dir}/)
yarn build

# Or build via bench (runs yarn build for all apps with frontends)
cd /path/to/frappe-bench
bench build --app {app_name}
```

---

## Key Integration Points

| What                           | How                                                                                         |
| ------------------------------ | ------------------------------------------------------------------------------------------- |
| API calls to Frappe            | `frappe-ui` resources (`createResource`, `createDocumentResource`, `createListResource`)    |
| SPA routing                    | `website_route_rules` in hooks.py + `createWebHistory("/{app_route}/")` in Vue Router       |
| Built assets                   | Vite outputs to `{app_name}/public/{frontend_dir}/` — served by Frappe's static file server |
| Boot data (user, translations) | `jinjaBootData: true` in Vite plugin + dev-mode API fallback                                |
| App launcher                   | `add_to_apps_screen` in hooks.py                                                            |
| Realtime updates               | `socket.io-client` connecting to Frappe's socketio server                                   |

---

## Source References

> **AI INSTRUCTION:** Do NOT read these files during normal skill execution. They are listed here ONLY for updating this skill.

- `apps/helpdesk/desk/vite.config.js` — Canonical Vite config with `frappeui()` plugin, PWA, JSX
- `apps/helpdesk/desk/package.json` — Full dependency list (frappe-ui 0.1.192, pinia, dayjs, echarts, etc.)
- `apps/helpdesk/desk/src/main.js` — Bootstrap pattern with dev-mode boot data, global components, socket init
- `apps/helpdesk/desk/src/router/index.ts` — Vue Router with `createWebHistory`, auth guards, lazy imports
- `apps/helpdesk/desk/src/socket.ts` — Socket.io client initialization
- `apps/helpdesk/desk/tailwind.config.js` — Tailwind config extending frappe-ui preset
- `apps/helpdesk/helpdesk/hooks.py` — `website_route_rules`, `add_to_apps_screen` for SPA integration