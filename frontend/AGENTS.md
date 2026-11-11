# AGENTS.md: the Vue frontend

Rules for `frontend/`: Vue 3, Vite, Composition API, frappe-ui, TailwindCSS and bpmn-js. The build lands in `one_bpmn/public/frontend/` (shell `one_bpmn/www/processa.html`) and is served at `/processa`. Components are already large; resist adding to them.

## Layout

- `src/pages/`: routed pages (`Processes.vue`, `Process.vue`, `Instances.vue`, `Instance.vue`, and the agent pages such as `Runs.vue`, `Evals.vue`, `A2A.vue`). Routes are in `src/router.js`.
- `src/components/`: the editor (`BpmnEditor.vue`, `FormattingToolbar.vue`), dialogs, Logix (`LogixCanvas.vue`, `LogixChat.vue`), ProsAlly (`ProsAllyPanel.vue`) and the shared chat panel under `components/Chat/`.
- `src/composables/`: shared logic, named `use<Name>`.
- `src/bpmn/`: bpmn-js extensions, with the properties panel providers at its top level and `renderers/`, `rules/`, `resize/`, `moddle/` and `lint/` beside them. The properties panel is Preact and keeps its shared components in `src/bpmn/shared/`.
- `src/utils/bpmnLayout.js`: the auto-layout for generated diagrams. `src/bpmn/lint/bpmnlintrc.js`: the bpmnlint rules. `tools/bpmn-pipeline/`: the IR-to-BPMN compiler ProsAlly runs. `pipeline.mjs` only reads the IR and chains the steps, one file each: `normalise.mjs`, `lanes.mjs`, `subprocesses.mjs`, `layout.mjs` and `compile.mjs`, with `shared.mjs` for what more than one step uses.

Register a bpmn-js module in `additionalModules` and a moddle extension in `moddleExtensions` in `BpmnEditor.vue`.

## Vue

- `<script setup>` only; no Options API.
- With `lang="ts"`, type `defineProps` and `defineEmits`; plain JS components may keep runtime prop validation.
- Derived state in `computed()`, not methods or template expressions.
- `shallowRef` for large objects such as the bpmn-js modeler.
- `:key` on every `v-for`; never `v-if` and `v-for` on one element.
- Remove bpmn-js event listeners in `onBeforeUnmount`.
- Each component sits in a folder named after it (`components/Docu/DocuApplyBar/DocuApplyBar.vue`) with its own `.css` beside it (rule component-folder).
- Composables are `use<Name>.js`: the five large families live in `composables/<Area>/` (`Docu`, `Eval`, `AgentConfig`, `Process`, `Editor`, each file starting with `use<Area>`), the rest stay at the root (rule composable-layout).
- Flag a component with more than 300 lines of `<script setup>`, a function over 30 lines, or a template nested more than three `div` levels; split or extract.

## frappe-ui and Tailwind

- Every control in a page, dialog, panel or tab is a frappe-ui component (Dialog, Tabs, Button, FormControl, TextInput, Textarea, Select, Checkbox, Switch, Autocomplete, Badge). No native select, input, textarea or hand-styled chip (rule E9).
- Call the backend with `frappeRequest`, or `createResource` and `createListResource` when you need a reactive resource. The one exception is the streaming chat client `utils/aguiClient.js`, which reads Server-Sent Events with `fetch`.
- Icons are Lucide, from `@iconify-json/lucide` through `@iconify/vue`. No other icon library.
- Use Tailwind utilities and the tokens in `tailwind.config.cjs`; no hard-coded colours, and `@apply` only for a truly repeated pattern.

## bpmn-js and SpiffWorkflow extensions

For `src/bpmn/` (including `renderers/`, `rules/`, `resize/`, `moddle/` and `lint/`):

- A moddle extension change must still read every existing BPMN XML.
- A custom renderer handles missing or null element properties.
- A custom rule never silently blocks a valid BPMN operation.
- Prefer configuring an existing bpmn-js feature over a new module, and do not add a module that duplicates one bpmn-js already has.

## Logix canvas (`LogixCanvas.vue`)

- `elementLabel` is a `computed()`, so it follows the user to another task.
- Changing the code schedules a save (`scheduleAutoSave`, 1500 ms debounce) that upserts the script through `create_server_script` and links it to the BPMN element.
- Never show the security validator's violation list; show only the failure message.

## ProsAlly panel (`ProsAllyPanel.vue`)

- The panel is a flex sibling of the canvas, so the canvas shrinks while it is open.
- A "Yes, proceed" on a confirmation re-sends the turn with `confirmedAction` set; a confirmed modify also sends the canvas XML from `getCanvasXml()`.
- A generated or modified diagram goes through `BpmnEditor.onProsAllyBpmnGenerated(xml)`, which runs `layoutBpmnXml(xml)` and then loads the result.

`layoutBpmnXml` places elements by column from the start event (BFS, joins moved past their last incoming column, back edges skipped), 160 px apart horizontally and 120 px vertically around y = 300, and writes every `BPMNShape` and `BPMNEdge`, creating any that are missing. Sizes: events 36x36, tasks 100x80, gateways 50x50, sub-processes 200x120. On a parser error it returns the XML unchanged, so callers must cope with an un-laid-out diagram.
