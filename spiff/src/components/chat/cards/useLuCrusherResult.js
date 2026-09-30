// Shared computed logic behind LuCrusherResultCard / LuCrusherResultBody
// (WI-003115 split): the small card and the #expanded dialog body render
// the identical payload, so the intent -> panel decision, the title and
// the "is there anything to show" gate live in one place instead of two
// copies that could quietly drift apart.
import { computed } from "vue";

const __ = (window.__ && typeof window.__ === "function") ? window.__ : (s) => s;

export const TASK_COLUMNS = [
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

export function refs(references) {
	const list = Array.isArray(references)
		? references
		: typeof references === "string" && references
			? references.split(",").map((r) => r.trim())
			: [];
	return list.slice(0, 3).join(", ");
}

export function matchName(match, i) {
	return match.process_name || match.name || `Match ${i + 1}`;
}

export function matchDesc(match) {
	return match.description || match.process_type || "";
}

export function useLuCrusherResult(props) {
	const intent = computed(() => props.value.intent || "");
	const panel = computed(() => PANEL_BY_INTENT[intent.value] || "");
	const confirmed = computed(() => intent.value.endsWith("_CONFIRMED"));

	const matches = computed(() => props.value.matches || []);
	const doc = computed(() => props.value.document || {});
	const scan = computed(() => props.value.codebase_scan || {});
	const topology = computed(() => props.value.topology || {});
	const processes = computed(() => topology.value.processes || []);

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

	const stageActions = computed(() => (STAGE_ACTIONS[panel.value] || {}).actions || []);
	const confirmedLabel = computed(() => __((STAGE_ACTIONS[panel.value] || {}).confirmedLabel || "Confirmed"));
	// Suggestions are live-stream chrome: a replayed transcript shows the panel
	// without re-offering next steps that have already been taken.
	const suggestions = computed(() => SUGGESTIONS[intent.value] || []);

	const hasContent = computed(
		() => !!panel.value || !!stageActions.value.length || !!suggestions.value.length
	);

	return {
		__,
		TASK_COLUMNS,
		intent,
		panel,
		confirmed,
		matches,
		doc,
		scan,
		topology,
		processes,
		taskProcesses,
		promptProcesses,
		title,
		swimlanes,
		doctypes,
		hooks,
		files,
		stageActions,
		confirmedLabel,
		suggestions,
		hasContent,
		refs,
		matchName,
		matchDesc,
	};
}
