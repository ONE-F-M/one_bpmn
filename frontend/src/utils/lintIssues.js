// The linter's findings as one list ProsAlly reads: errors first, each with the element it is about.
export function flattenLintIssues(issuesByElement, limit = 40) {
	const findings = [];
	for (const reports of Object.values(issuesByElement || {})) {
		for (const report of reports) {
			findings.push({
				id: report.actualElementId || report.id,
				rule: report.rule || "",
				message: report.message || "",
				category: report.category || "warn",
			});
		}
	}
	findings.sort((a, b) => Number(b.category === "error") - Number(a.category === "error"));
	return findings.slice(0, limit);
}

/** The readiness checklist with every error-level lint report added as a missing check, so Deploy stays disabled. */
export function withLintErrors(checklist, issuesByRule) {
	const errors = Object.values(issuesByRule || {})
		.flat()
		.filter((report) => report.category === "error");
	if (!errors.length) {
		return checklist;
	}
	const items = errors.map((report) => ({ name: report.message, exists: false, type: "check" }));
	return {
		...checklist,
		categories: [...(checklist.categories || []), { label: "Linting Errors", icon: "alert-circle", items }],
		total_checked: checklist.total_checked + items.length,
		total_missing: checklist.total_missing + items.length,
		all_ready: false,
	};
}

const CONTAINMENT_KEYS = [
	"flowElements",
	"laneSets",
	"lanes",
	"artifacts",
	"eventDefinitions",
	"participants",
	"messageFlows",
	"processRef",
	"rootElements",
];

function descendantIds(bo, ids = new Set(), visited = new Set()) {
	if (!bo || typeof bo !== "object" || visited.has(bo)) {
		return ids;
	}
	visited.add(bo);
	if (bo.id) {
		ids.add(bo.id);
	}
	for (const key of CONTAINMENT_KEYS) {
		const value = bo[key];
		for (const child of Array.isArray(value) ? value : [value]) {
			descendantIds(child, ids, visited);
		}
	}
	return ids;
}

/** The lint reports about elements on the plane the canvas shows: a process, a collaboration's pools, or a drilled-down subprocess. */
export function issuesOnPlane(issuesByElement, rootBo) {
	const ids = descendantIds(rootBo);
	// An empty canvas has only its root, which the linter would flag for a missing start and end event.
	if (ids.size <= 1) {
		return {};
	}
	const shown = {};
	for (const [elementId, reports] of Object.entries(issuesByElement)) {
		const kept = reports.filter((report) => ids.has(report.actualElementId || report.id));
		if (kept.length) {
			shown[elementId] = kept;
		}
	}
	return shown;
}
