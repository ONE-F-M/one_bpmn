<template>
	<!-- Phases like CLARIFY or NO_MATCH carry no panel, no stage action and no
	     next step — their whole answer is the reply text, so the card renders
	     nothing rather than an empty shell above it. -->
	<CardShell v-if="hasContent" :title="title">
		<Stack :gap="10">
			<!-- EXACT_MATCH_FOUND / MULTIPLE_MATCHES ─────────────────────── -->
			<Stack v-if="panel === 'matches'" :gap="6">
				<Row v-for="(m, i) in matches" :key="i" :gap="8" class="lcr-row">
					<Stack :gap="2" class="lcr-grow">
						<Heading :text="matchName(m, i)" />
						<TextBlock v-if="matchDesc(m)" class="lcr-sub">{{ matchDesc(m) }}</TextBlock>
					</Stack>
					<ActionButton :label="__('Select')" kind="solid" :disabled="busy" @press="quickSend(matchName(m, i))" />
				</Row>
			</Stack>

			<!-- LUCIDCHART_PARSED ────────────────────────────────────────── -->
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

			<!-- CODEBASE_SCAN_RESULT ─────────────────────────────────────── -->
			<Stack v-else-if="panel === 'scan'" :gap="8">
				<Row :gap="6">
					<span class="lcr-stat">{{ (scan.apps_scanned || []).length }} {{ __("apps") }}</span>
					<span class="lcr-stat">{{ doctypes.length }} {{ __("DocTypes matched") }}</span>
					<span class="lcr-stat">{{ hooks.length }} {{ __("hooks") }}</span>
					<span class="lcr-stat">{{ files.length }} {{ __("controller files") }}</span>
				</Row>
				<details v-if="doctypes.length" class="lcr-details">
					<summary>{{ __("DocTypes") }} ({{ doctypes.length }})</summary>
					<Stack :gap="2" class="lcr-scroll">
						<Row v-for="(d, i) in doctypes.slice(0, 20)" :key="i" :gap="6">
							<span class="lcr-name">{{ d.name }}</span>
							<span v-if="d.note" class="lcr-sub">{{ d.note }}</span>
						</Row>
					</Stack>
				</details>
				<details v-if="hooks.length" class="lcr-details">
					<summary>{{ __("Hooks / doc_events") }} ({{ hooks.length }})</summary>
					<Stack :gap="2" class="lcr-scroll">
						<code v-for="(h, i) in hooks.slice(0, 12)" :key="i" class="lcr-code">{{ h }}</code>
					</Stack>
				</details>
				<details v-if="files.length" class="lcr-details">
					<summary>{{ __("Controller files") }} ({{ files.length }})</summary>
					<Stack :gap="2" class="lcr-scroll">
						<Row v-for="(f, i) in files.slice(0, 10)" :key="i" :gap="6">
							<code class="lcr-code">{{ f.path }}</code>
							<span v-if="f.note" class="lcr-sub">{{ f.note }}</span>
						</Row>
					</Stack>
				</details>
			</Stack>

			<!-- TOPOLOGY_PROPOSAL / TOPOLOGY_CONFIRMED ───────────────────── -->
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

			<!-- MIGRATION_TASKS_DRAFT / MIGRATION_TASKS_CONFIRMED ────────── -->
			<Stack v-else-if="panel === 'tasks'" :gap="8">
				<details v-for="(proc, pi) in taskProcesses" :key="pi" class="lcr-details" :open="pi === 0">
					<summary>{{ proc.name }} <span class="lcr-sub">({{ proc.count }} {{ __("tasks") }})</span></summary>
					<Stack :gap="8">
						<DataTable
							v-for="(group, gi) in proc.categories"
							:key="gi"
							:title="group.category"
							:columns="TASK_COLUMNS"
							:rows="group.rows"
						/>
					</Stack>
				</details>
			</Stack>

			<!-- PROSALLY_PROMPT_DRAFT / PROSALLY_PROMPT_CONFIRMED ────────── -->
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
						<ActionButton :label="copied === i ? __('Copied') : __('Copy prompt')" @press="copy(p.prompt_block, i)" />
					</Row>
				</Stack>
			</Stack>

			<!-- Confirm / request-changes, then the contextual next steps ── -->
			<Row v-if="stageActions.length && !confirmed" :gap="8">
				<ActionButton
					v-for="(a, i) in stageActions"
					:key="i"
					:label="a.label"
					:kind="i === 0 ? 'solid' : 'outline'"
					:disabled="busy"
					@press="quickSend(a.message)"
				/>
			</Row>
			<div v-else-if="confirmed" class="lcr-confirmed">✓ {{ confirmedLabel }}</div>

			<Stack v-if="suggestions.length" :gap="4">
				<span class="lcr-label">{{ __("What would you like to do next?") }}</span>
				<Row :gap="6">
					<ActionButton
						v-for="(s, i) in suggestions"
						:key="i"
						:label="`${s.icon} ${s.label}`"
						:disabled="busy"
						@press="quickSend(s.message)"
					/>
				</Row>
			</Stack>
		</Stack>
	</CardShell>
</template>
<script setup>
// LuCrusherResultCard (WI-001678) = CardShell[Stack[…]] over the six panels
// lumina.js rendered by hand for onefm.lucrusher_result: process matches, a
// parsed Lucidchart document, a codebase scan, the topology proposal, the
// migration task list and the ProsAlly prompts. Which panel shows is decided
// by the payload's `intent`, exactly as handle_lucrusher_result decided it.
//
// Every button is a QUICK-SEND: it puts a literal sentence in the composer
// and sends it, which is all the legacy data-lcr-send buttons ever did. The
// sentences are copied verbatim from lumina.js — LuCrusher reads them as
// intent, so paraphrasing them would silently change the conversation.
import { computed, ref } from "vue";
import ActionButton from "../primitives/ActionButton.vue";
import CardShell from "../primitives/CardShell.vue";
import CodeBlock from "../primitives/CodeBlock.vue";
import DataTable from "../primitives/DataTable.vue";
import Heading from "../primitives/Heading.vue";
import Row from "../primitives/Row.vue";
import Stack from "../primitives/Stack.vue";
import TextBlock from "../primitives/TextBlock.vue";

const props = defineProps({
	value: { type: Object, required: true },
	busy: { type: Boolean, default: false },
});
const emit = defineEmits(["action"]);

const __ = (window.__ && typeof window.__ === "function") ? window.__ : (s) => s;

const TASK_COLUMNS = [
	{ key: "index", label: "#", align: "right" },
	{ key: "task", label: "Task" },
	{ key: "detail", label: "Detail" },
	{ key: "references", label: "References" },
];

// intent → panel, mirroring handle_lucrusher_result's if/else ladder.
const PANEL_BY_INTENT = {
	EXACT_MATCH_FOUND: "matches",
	MULTIPLE_MATCHES: "matches",
	LUCIDCHART_PARSED: "document",
	CODEBASE_SCAN_RESULT: "scan",
	TOPOLOGY_PROPOSAL: "topology",
	TOPOLOGY_CONFIRMED: "topology",
	MIGRATION_TASKS_DRAFT: "tasks",
	MIGRATION_TASKS_CONFIRMED: "tasks",
	PROSALLY_PROMPT_DRAFT: "prosally",
	PROSALLY_PROMPT_CONFIRMED: "prosally",
};

const SUGGESTIONS = {
	CONFIRMED: [{ icon: "📄", label: "Paste the Lucidchart link", message: "Here is the Lucidchart link:" }],
	LUCIDCHART_PARSED: [
		{ icon: "🔬", label: "Scan the codebase", message: "scan the codebase for this process" },
		{ icon: "🏗️", label: "Analyse the topology", message: "analyse the topology for this process" },
	],
	CODEBASE_SCAN_RESULT: [{ icon: "🏗️", label: "Analyse the topology", message: "analyse the topology" }],
	TOPOLOGY_CONFIRMED: [{ icon: "📋", label: "Generate migration tasks", message: "generate the migration task list" }],
	MIGRATION_TASKS_CONFIRMED: [{ icon: "🎨", label: "Generate ProsAlly prompts", message: "generate ProsAlly prompts" }],
};

const STAGE_ACTIONS = {
	topology: {
		confirmedLabel: "Topology confirmed",
		actions: [
			{ label: "✓ Approve topology", message: "yes, the topology looks good" },
			{ label: "✏️ Request changes", message: "I'd like to suggest some changes to the topology" },
		],
	},
	tasks: {
		confirmedLabel: "Task list confirmed",
		actions: [
			{ label: "✓ Confirm task list", message: "yes, the task list looks good, confirmed" },
			{ label: "✏️ Request changes", message: "I'd like to modify some tasks" },
		],
	},
	prosally: {
		confirmedLabel: "ProsAlly prompts confirmed",
		actions: [
			{ label: "✓ Confirm prompts", message: "yes, the ProsAlly prompts look good, confirmed" },
			{ label: "✏️ Request changes", message: "I'd like to adjust one of the ProsAlly prompts" },
		],
	},
};

const intent = computed(() => props.value.intent || "");
const panel = computed(() => PANEL_BY_INTENT[intent.value] || "");
const confirmed = computed(() => intent.value.endsWith("_CONFIRMED"));

const matches = computed(() => props.value.matches || []);
const doc = computed(() => props.value.document || {});
const scan = computed(() => props.value.codebase_scan || {});
const topology = computed(() => props.value.topology || {});
const processes = computed(() => topology.value.processes || []);

const title = computed(() => {
	const plural = (n) => (n === 1 ? "process" : "processes");
	if (panel.value === "matches") return __("🔍 Process matches");
	if (panel.value === "document") return `📄 ${__("Lucidchart")}: ${doc.value.title || doc.value.document_id || __("Document")}`;
	if (panel.value === "scan") return __("🔬 Codebase scan results");
	if (panel.value === "topology") {
		const rec = topology.value.recommendation ? ` — ${topology.value.recommendation}` : "";
		return `🏗️ ${__("Topology")}${rec} · ${processes.value.length} ${plural(processes.value.length)}`;
	}
	if (panel.value === "tasks") {
		const total = taskProcesses.value.reduce((acc, p) => acc + p.count, 0);
		return `📋 ${__("Migration tasks")} — ${total} ${__("tasks across")} ${taskProcesses.value.length} ${plural(taskProcesses.value.length)}`;
	}
	if (panel.value === "prosally") {
		return `🎨 ${__("ProsAlly prompts")} — ${promptProcesses.value.length} ${plural(promptProcesses.value.length)}`;
	}
	return __("LuCrusher");
});

// Swimlane names are plain strings on some documents and objects on others.
const swimlanes = computed(() => {
	const names = [];
	for (const page of doc.value.pages || []) {
		for (const lane of page.swimlanes || []) {
			const name = typeof lane === "string" ? lane : lane.label || lane.name || lane.text || lane.title || "";
			if (name && !names.includes(name)) names.push(name);
		}
	}
	return names;
});

// The scan lists arrive as strings or as objects, per entry — normalise once
// so the template stays a template.
const doctypes = computed(() =>
	(scan.value.matched_doctypes || []).map((d) =>
		typeof d === "string" ? { name: d, note: "" } : { name: d.doctype || d.name || "", note: d.relevance || d.reason || "" }
	)
);
const hooks = computed(() =>
	(scan.value.hooks_found || []).map((h) => (typeof h === "string" ? h : JSON.stringify(h)).substring(0, 150))
);
const files = computed(() =>
	(scan.value.controller_files || []).map((f) =>
		typeof f === "string" ? { path: f, note: "" } : { path: f.path || f.file || "", note: f.note || f.relevance || "" }
	)
);

const taskProcesses = computed(() =>
	((props.value.migration_tasks || {}).processes || []).map((proc, pi) => {
		const tasks = proc.tasks || [];
		const byCategory = {};
		tasks.forEach((t) => {
			const category = t.category || "General";
			(byCategory[category] = byCategory[category] || []).push(t);
		});
		return {
			name: proc.process_name || `Process ${pi + 1}`,
			count: tasks.length,
			categories: Object.entries(byCategory).map(([category, rows]) => ({
				category,
				rows: rows.map((t, ti) => ({
					index: ti + 1,
					task: `${t.is_new === true || t.is_new === "true" ? "🆕" : "♻️"} ${t.task || t.name || ""}`,
					detail: t.detail || t.description || "",
					references: refs(t.references),
				})),
			})),
		};
	})
);
const promptProcesses = computed(() => (props.value.prosally_prompts || {}).processes || []);

const stageActions = computed(() => (STAGE_ACTIONS[panel.value] || {}).actions || []);
const confirmedLabel = computed(() => __((STAGE_ACTIONS[panel.value] || {}).confirmedLabel || "Confirmed"));
// Suggestions are live-stream chrome: a replayed transcript shows the panel
// without re-offering next steps that have already been taken.
const suggestions = computed(() => SUGGESTIONS[intent.value] || []);

const hasContent = computed(
	() => !!panel.value || !!stageActions.value.length || !!suggestions.value.length
);

const copied = ref(-1);

function refs(references) {
	const list = Array.isArray(references)
		? references
		: typeof references === "string" && references
			? references.split(",").map((r) => r.trim())
			: [];
	return list.slice(0, 3).join(", ");
}

function matchName(match, i) {
	return match.process_name || match.name || `Match ${i + 1}`;
}

function matchDesc(match) {
	return match.description || match.process_type || "";
}

function quickSend(message) {
	emit("action", "quick-send", { message });
}

function copy(text, i) {
	navigator.clipboard.writeText(text || "").then(() => {
		copied.value = i;
		setTimeout(() => (copied.value = -1), 1500);
	});
}
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
.lcr-confirmed { font-size: 12px; color: #278f5e; }
:global([data-theme="dark"]) .lcr-row, :global([data-theme="dark"]) .lcr-proc { border-color: #343434; }
:global([data-theme="dark"]) .lcr-stat { background: #2b2b2b; color: #999; }
:global([data-theme="dark"]) .lcr-chip { background: #343434; color: #d4d4d4; }
:global([data-theme="dark"]) .lcr-name { color: #d4d4d4; }
:global([data-theme="dark"]) .lcr-num { background: #f8f8f8; color: #0f0f0f; }
:global([data-theme="dark"]) .lcr-sub, :global([data-theme="dark"]) .lcr-code { color: #808080; }
</style>
