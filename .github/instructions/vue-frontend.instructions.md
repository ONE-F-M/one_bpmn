---
applyTo:
  - "spiff/**/*.vue"
  - "spiff/**/*.js"
  - "spiff/**/*.ts"
---

# Vue.js Frontend Review

Vue 3 + Vite + Composition API + frappe-ui + TailwindCSS + bpmn-js.
Components are already large. Resist further bloat.

## Code Size

- Flag components over 300 lines of `<script setup>`. Split them.
- Flag functions over 30 lines. Extract composables or utilities.
- Flag `<template>` with more than 3 nested div levels. Simplify or extract sub-components.

## Vue 3 Patterns

- MUST use `<script setup>` (Composition API). Flag Options API.
- In `<script setup lang="ts">`, use `defineProps`/`defineEmits` with TypeScript types instead of runtime validation; in JS components, runtime prop validation is acceptable until the codebase is migrated to TypeScript.
- Prefer `computed()` over methods for derived state.
- Prefer `watchEffect()` over `watch()` when dependencies are obvious.
- Use `shallowRef` for large objects (bpmn-js modeler) to avoid deep reactivity.
- No `v-if` + `v-for` on the same element.

## frappe-ui

- Prefer `frappeRequest` for API calls. Use `createResource`/`createListResource` when you need reactive frappe-ui resources. Flag new/raw `fetch`/`axios` usage unless there is a clear, documented reason.
- Use frappe-ui components (Button, Dialog, TextInput) over custom implementations.
- Reuse Lucide icons from `@iconify-json/lucide`. No new icon libraries.

## Tailwind

- Use utility classes directly. Flag custom CSS that replicates Tailwind utilities.
- Use `@apply` sparingly — only for truly repeated patterns.
- Flag hardcoded color values. Use design tokens from tailwind.config.cjs.

## Performance

- Clean up bpmn-js event listeners in `onBeforeUnmount`.
- Flag `v-for` without `:key`.
- Move expensive computations from `<template>` to `computed()`.
