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
