import lintModule from "bpmn-js-bpmnlint";
import "bpmn-js-bpmnlint/dist/assets/css/bpmn-js-bpmnlint.css";
import bpmnlintConfig from "@/bpmn/lint/bpmnlintrc.js";

export { lintModule, bpmnlintConfig };

import { nextTick } from "vue";
import { watchAgentConfigLint } from "@/composables/AgentConfig/useAgentConfigLintState";
import { flattenLintIssues } from "@/utils/lintIssues.js";

export function useEditorLint(ed) {
	const { props, showProsAllyPanel, prosAllyPanel } = ed;

	async function getLintIssues() {
		const linting = ed.modeler?.get("linting");
		if (!linting) return [];
		return flattenLintIssues(linting._formatIssues(await linting.lint()));
	}

	async function getRawLintIssues() {
		const linting = ed.modeler?.get("linting");
		return linting ? await linting.lint() : {};
	}

	async function explainLintFinding(entry) {
		if (props.readonly) return;
		showProsAllyPanel.value = true;
		await nextTick();
		await nextTick();
		const id = entry.actualElementId || entry.id;
		await prosAllyPanel.value?.ask(
			`Diagnose this lint finding on ${id} and suggest a remedy: ${entry.message} (${entry.rule})`,
		);
	}

	ed.onReady(() => {
		const eventBus = ed.modeler.get("eventBus");
		const linting = ed.modeler.get("linting");
		if (linting) {
			const originalFormatIssues = linting._formatIssues;
			linting._formatIssues = function (issues) {
				let formattedIssues = originalFormatIssues.call(this, issues);

				try {
					const canvas = ed.modeler.get("canvas");
					const rootElement = canvas.getRootElement();

					// Implicit roots (empty canvas) have no businessObject -
					// guard so the filter degrades to "no issues" instead of throwing.
					const rootBo = rootElement.businessObject;
					const flowEls = (rootBo && rootBo.flowElements) || [];
					if (!flowEls.length) {
						return {};
					}

					// Helper to collect all element IDs strictly contained within the given moddle object
					const getModdleDescendants = (
						bo,
						descendants = new Set(),
						visited = new Set(),
					) => {
						if (!bo || typeof bo !== "object") return descendants;
						if (visited.has(bo)) return descendants;
						visited.add(bo);

						if (bo.id) descendants.add(bo.id);

						const containmentKeys = [
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

						for (const key of containmentKeys) {
							const val = bo[key];
							if (Array.isArray(val)) {
								val.forEach((child) =>
									getModdleDescendants(child, descendants, visited),
								);
							} else if (val && typeof val === "object") {
								getModdleDescendants(val, descendants, visited);
							}
						}
						return descendants;
					};

					const validIds = getModdleDescendants(rootElement.businessObject);

					for (const elementId in formattedIssues) {
						const issueGroup = formattedIssues[elementId];
						// Filter reports to ensure their actual element is a descendant
						const filteredGroup = issueGroup.filter((report) => {
							const actualId = report.actualElementId || report.id;
							return validIds.has(actualId);
						});

						if (filteredGroup.length === 0) {
							delete formattedIssues[elementId];
						} else {
							formattedIssues[elementId] = filteredGroup;
						}
					}
				} catch (err) {
					console.warn(
						"[bpmnlint] _formatIssues filter failed, returning unfiltered issues:",
						err,
					);
				}

				return formattedIssues;
			};

			const originalAddEntry = linting._addEntry;
			linting._addEntry = function ($ul, state, entry) {
				originalAddEntry.call(this, $ul, state, entry);
				const button = document.createElement("button");
				button.type = "button";
				button.className = "bjsl-explain btn btn-xs btn-default";
				button.textContent = window.__
					? window.__("Explain this error")
					: "Explain this error";
				button.addEventListener("click", (event) => {
					event.stopPropagation();
					explainLintFinding(entry);
				});
				$ul.lastElementChild?.appendChild(button);
			};

			// Rerun linting when drilling down/up so the panel stays relevant to current plane
			eventBus.on("root.set", () => {
				linting.update();
			});
			watchAgentConfigLint(ed.modeler);
		}
	});

	Object.assign(ed, { getLintIssues, getRawLintIssues, explainLintFinding });
}
