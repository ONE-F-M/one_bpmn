// Pure derivation of the LuCrusherResultCard view model from the raw
// onefm.lucrusher_result payload (WI-001678, extended WI-003124). Kept out
// of the .vue files so both the small-card body and the #expanded dialog
// body (LuCrusherResultBody.vue, rendered twice by LuCrusherResultCard.vue)
// compute the exact same thing from the exact same `value` prop, and so the
// host wrapper can read `title`/`hasContent` without duplicating the
// intent → panel ladder.
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

export function deriveLuCrusherView(value) {
	const intent = value.intent || "";
	const panel = PANEL_BY_INTENT[intent] || "";
	const confirmed = intent.endsWith("_CONFIRMED");

	const matches = value.matches || [];
	const doc = value.document || {};
	const scan = value.codebase_scan || {};
	const topology = value.topology || {};
	const processes = topology.processes || [];

	const swimlanes = [];
	for (const page of doc.pages || []) {
		for (const lane of page.swimlanes || []) {
			const name = typeof lane === "string" ? lane : lane.label || lane.name || lane.text || lane.title || "";
			if (name && !swimlanes.includes(name)) swimlanes.push(name);
		}
	}

	const doctypes = (scan.matched_doctypes || []).map((d) =>
		typeof d === "string" ? { name: d, note: "" } : { name: d.doctype || d.name || "", note: d.relevance || d.reason || "" }
	);
	const hooks = (scan.hooks_found || []).map((h) => (typeof h === "string" ? h : JSON.stringify(h)).substring(0, 150));
	const files = (scan.controller_files || []).map((f) =>
		typeof f === "string" ? { path: f, note: "" } : { path: f.path || f.file || "", note: f.note || f.relevance || "" }
	);

	const taskProcesses = ((value.migration_tasks || {}).processes || []).map((proc, pi) => {
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
	});

	const promptProcesses = (value.prosally_prompts || {}).processes || [];
	const stageActions = (STAGE_ACTIONS[panel] || {}).actions || [];
	const confirmedLabel = __((STAGE_ACTIONS[panel] || {}).confirmedLabel || "Confirmed");
	const suggestions = SUGGESTIONS[intent] || [];

	const plural = (n) => (n === 1 ? "process" : "processes");
	let title = __("LuCrusher");
	if (panel === "matches") title = __("🔍 Process matches");
	else if (panel === "document") title = `📄 ${__("Lucidchart")}: ${doc.title || doc.document_id || __("Document")}`;
	else if (panel === "scan") title = __("🔬 Codebase scan results");
	else if (panel === "topology") {
		const rec = topology.recommendation ? ` — ${topology.recommendation}` : "";
		title = `🏗️ ${__("Topology")}${rec} · ${processes.length} ${plural(processes.length)}`;
	} else if (panel === "tasks") {
		const total = taskProcesses.reduce((acc, p) => acc + p.count, 0);
		title = `📋 ${__("Migration tasks")} — ${total} ${__("tasks across")} ${taskProcesses.length} ${plural(taskProcesses.length)}`;
	} else if (panel === "prosally") {
		title = `🎨 ${__("ProsAlly prompts")} — ${promptProcesses.length} ${plural(promptProcesses.length)}`;
	}

	const hasContent = !!panel || !!stageActions.length || !!suggestions.length;

	return {
		intent, panel, confirmed, matches, doc, scan, topology, processes, swimlanes,
		doctypes, hooks, files, taskProcesses, promptProcesses, stageActions,
		confirmedLabel, suggestions, hasContent, title,
	};
}
