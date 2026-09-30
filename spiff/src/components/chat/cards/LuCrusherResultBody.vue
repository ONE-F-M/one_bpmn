<template>
	<Stack :gap="10" class="lcrb" :class="{ 'lcrb--expanded': expanded }">
		<!-- EXACT_MATCH_FOUND / MULTIPLE_MATCHES ───────────────────────── -->
		<Stack v-if="panel === 'matches'" :gap="6">
			<Row v-for="(m, i) in matches" :key="i" :gap="8" class="lcr-row">
				<Stack :gap="2" class="lcr-grow">
					<Heading :text="matchName(m, i)" />
					<TextBlock v-if="matchDesc(m)" class="lcr-sub">{{ matchDesc(m) }}</TextBlock>
				</Stack>
				<ActionButton :label="__('Select')" kind="solid" :disabled="busy" @press="$emit('quick-send', matchName(m, i))" />
			</Row>
		</Stack>

		<!-- LUCIDCHART_PARSED ───────────────────────────────────────────── -->
		<Stack v-else-if="panel === 'document'" :gap="8">
			<Row :gap="6">
				<span class="lcr-stat">{{ doc.page_count || 0 }} {{ __("pages") }}</span>
				<span class="lcr-stat">{{ doc.total_shapes || 0 }} {{ __("shapes") }}</span>
				<span class="lcr-stat">{{ doc.total_lines || 0 }} {{ __("connections") }}</span>
			</Row>
			<Row v-if="swimlanes.length" :gap="4">
				<span class="lcr-label">{{ __("Swimlanes") }}</span>
				<span v-for="(s, i) in swimlanes" :key="i" class="lcr-chip">{{ s }}</span>
			</Row>
		</Stack>

		<!-- CODEBASE_SCAN_RESULT ──────────────────────────────────────── -->
		<Stack v-else-if="panel === 'scan'" :gap="8">
			<Row :gap="6">
				<span class="lcr-stat">{{ (scan.apps_scanned || []).length }} {{ __("apps") }}</span>
				<span class="lcr-stat">{{ doctypes.length }} {{ __("DocTypes matched") }}</span>
				<span class="lcr-stat">{{ hooks.length }} {{ __("hooks") }}</span>
				<span class="lcr-stat">{{ files.length }} {{ __("controller files") }}</span>
			</Row>
			<details v-if="doctypes.length" class="lcr-details" :open="expanded">
				<summary>{{ __("DocTypes") }} ({{ doctypes.length }})</summary>
				<Stack :gap="2" class="lcr-scroll">
					<Row v-for="(d, i) in doctypes.slice(0, 20)" :key="i" :gap="6">
						<span class="lcr-name">{{ d.name }}</span>
						<span v-if="d.note" class="lcr-sub">{{ d.note }}</span>
					</Row>
				</Stack>
			</details>
			<details v-if="hooks.length" class="lcr-details" :open="expanded">
				<summary>{{ __("Hooks / doc_events") }} ({{ hooks.length }})</summary>
				<Stack :gap="2" class="lcr-scroll">
					<code v-for="(h, i) in hooks.slice(0, 12)" :key="i" class="lcr-code">{{ h }}</code>
				</Stack>
			</details>
			<details v-if="files.length" class="lcr-details" :open="expanded">
				<summary>{{ __("Controller files") }} ({{ files.length }})</summary>
				<Stack :gap="2" class="lcr-scroll">
					<Row v-for="(f, i) in files.slice(0, 10)" :key="i" :gap="6">
						<code class="lcr-code">{{ f.path }}</code>
						<span v-if="f.note" class="lcr-sub">{{ f.note }}</span>
					</Row>
				</Stack>
			</details>
		</Stack>

		<!-- TOPOLOGY_PROPOSAL / TOPOLOGY_CONFIRMED ─────────────────────── -->
		<Stack v-else-if="panel === 'topology'" :gap="8">
			<TextBlock v-if="topology.summary" class="lcr-summary">{{ topology.summary }}</TextBlock>
			<Stack :gap="6">
				<Row v-for="(p, i) in processes" :key="i" :gap="8" class="lcr-proc" :class="{ 'is-confirmed': confirmed }">
					<span class="lcr-num">{{ i + 1 }}</span>
					<Stack :gap="2" class="lcr-grow">
						<Heading :text="p.name || p.process_name || `Process ${i + 1}`" />
						<TextBlock v-if="p.type" class="lcr-type">{{ p.type }}</TextBlock>
						<TextBlock v-if="p.reason" class="lcr-sub">{{ p.reason }}</TextBlock>
						<Row v-if="(p.shapes || []).length" :gap="4">
							<span v-for="(s, si) in (p.shapes || []).slice(0, 6)" :key="si" class="lcr-chip">{{ s }}</span>
							<span v-if="(p.shapes || []).length > 6" class="lcr-sub">
								+{{ (p.shapes || []).length - 6 }} {{ __("more") }}
							</span>
						</Row>
					</Stack>
				</Row>
			</Stack>
		</Stack>

		<!-- MIGRATION_TASKS_DRAFT / MIGRATION_TASKS_CONFIRMED ─────────── -->
		<Stack v-else-if="panel === 'tasks'" :gap="8">
			<details v-for="(proc, pi) in taskProcesses" :key="pi" class="lcr-details" :open="expanded || pi === 0">
				<summary>{{ proc.name }} <span class="lcr-sub">({{ proc.count }} {{ __("tasks") }})</span></summary>
				<Stack :gap="8">
					<DataTable
						v-for="(group, gi) in proc.categories"
						:key="gi"
						:title="group.category"
						:columns="taskColumns"
						:rows="group.rows"
					/>
				</Stack>
			</details>
		</Stack>

		<!-- PROSALLY_PROMPT_DRAFT / PROSALLY_PROMPT_CONFIRMED ─────────── -->
		<Stack v-else-if="panel === 'prosally'" :gap="10">
			<Stack v-for="(p, i) in promptProcesses" :key="i" :gap="4">
				<Row :gap="6">
					<span class="lcr-num">{{ i + 1 }}</span>
					<Heading :text="p.process_name || `Process ${i + 1}`" />
					<span class="lcr-sub">
						{{ p.lane_count || "?" }} {{ __("lanes") }} · {{ p.element_count || "?" }} {{ __("elements") }}
					</span>
				</Row>
				<CodeBlock :code="p.prompt_block || ''" />
				<Row :gap="6">
					<ActionButton :label="copiedIndex === i ? __('Copied') : __('Copy prompt')" @press="$emit('copy', p.prompt_block, i)" />
				</Row>
			</Stack>
		</Stack>
	</Stack>
</template>
<script setup>
// LuCrusherResultBody (WI-003115): the six LuCrusher panels, shared between
// the small CardShell body and its #expanded dialog. The small card caps a
// long list at 220px (.lcr-scroll); the expanded dialog has room to show it
// all, so `expanded` lifts that cap and opens every <details> by default.
// Stage actions (approve/request-changes) and the "what next" suggestions
// stay out of this component — they live only on the small card, per the
// read-only-preview rule.
import ActionButton from "../primitives/ActionButton.vue";
import CodeBlock from "../primitives/CodeBlock.vue";
import DataTable from "../primitives/DataTable.vue";
import Heading from "../primitives/Heading.vue";
import Row from "../primitives/Row.vue";
import Stack from "../primitives/Stack.vue";
import TextBlock from "../primitives/TextBlock.vue";
import { matchName, matchDesc } from "./useLuCrusherResult.js";

const __ = (window.__ && typeof window.__ === "function") ? window.__ : (s) => s;

defineProps({
	panel: { type: String, default: "" },
	expanded: { type: Boolean, default: false },
	busy: { type: Boolean, default: false },
	confirmed: { type: Boolean, default: false },
	matches: { type: Array, default: () => [] },
	doc: { type: Object, default: () => ({}) },
	swimlanes: { type: Array, default: () => [] },
	scan: { type: Object, default: () => ({}) },
	doctypes: { type: Array, default: () => [] },
	hooks: { type: Array, default: () => [] },
	files: { type: Array, default: () => [] },
	topology: { type: Object, default: () => ({}) },
	processes: { type: Array, default: () => [] },
	taskProcesses: { type: Array, default: () => [] },
	taskColumns: { type: Array, default: () => [] },
	promptProcesses: { type: Array, default: () => [] },
	copiedIndex: { type: Number, default: -1 },
});
defineEmits(["quick-send", "copy"]);
</script>
<style scoped>
.lcr-grow { flex: 1; min-width: 0; }
.lcr-row { border: 1px solid #ededed; border-radius: 8px; padding: 6px 8px; }
.lcr-sub { font-size: 11.5px; color: #7c7c7c; }
.lcr-type { font-size: 11px; text-transform: uppercase; letter-spacing: 0.05em; color: #7c7c7c; }
.lcr-summary { font-size: 12.5px; color: #525252; }
.lcr-label { font-size: 10px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.05em; color: #7c7c7c; }
.lcr-stat { height: 20px; padding: 0 8px; border-radius: 99px; background: #f3f3f3; font-size: 11.5px; color: #525252; }
.lcr-chip { height: 20px; padding: 0 8px; border-radius: 99px; background: #ededed; font-size: 11.5px; color: #383838; }
.lcr-name { font-size: 12.5px; color: #383838; }
.lcr-code { font-family: ui-monospace, Menlo, monospace; font-size: 11px; color: #525252; }
.lcr-num { display: grid; place-items: center; width: 18px; height: 18px; border-radius: 99px;
	background: #171717; color: #fff; font-size: 10px; flex: none; }
.lcr-proc { align-items: flex-start; border: 1px solid #ededed; border-radius: 8px; padding: 6px 8px; }
.lcr-proc.is-confirmed { border-color: #278f5e; }
.lcr-details > summary { font-size: 12px; font-weight: 600; cursor: pointer; padding: 2px 0; }
.lcr-scroll { max-height: 220px; overflow-y: auto; padding: 4px 0 0; }
.lcrb--expanded .lcr-scroll { max-height: none; }
:global([data-theme="dark"]) .lcr-row, :global([data-theme="dark"]) .lcr-proc { border-color: #343434; }
:global([data-theme="dark"]) .lcr-stat { background: #2b2b2b; color: #999; }
:global([data-theme="dark"]) .lcr-chip { background: #343434; color: #d4d4d4; }
:global([data-theme="dark"]) .lcr-name { color: #d4d4d4; }
:global([data-theme="dark"]) .lcr-num { background: #f8f8f8; color: #0f0f0f; }
:global([data-theme="dark"]) .lcr-sub, :global([data-theme="dark"]) .lcr-code { color: #808080; }
</style>
