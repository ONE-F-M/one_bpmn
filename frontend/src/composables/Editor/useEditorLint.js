import lintModule from "bpmn-js-bpmnlint";
import "bpmn-js-bpmnlint/dist/assets/css/bpmn-js-bpmnlint.css";
import bpmnlintConfig from "@/bpmn/lint/bpmnlintrc.js";

export { lintModule, bpmnlintConfig };

import { nextTick } from "vue";
import { watchAgentConfigLint } from "@/composables/AgentConfig/useAgentConfigLintState";
import { flattenLintIssues, issuesOnPlane } from "@/utils/lintIssues.js";

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
				const rootBo = ed.modeler.get("canvas").getRootElement().businessObject;
				return issuesOnPlane(originalFormatIssues.call(this, issues), rootBo);
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

			// Keep details open after a click (the library only opens them on hover)
			ed.modeler.get("canvas")._container.addEventListener("click", (event) => {
				const icon = event.target.closest(".bjsl-icon");
				if (!icon) return;
				const overlay = icon.closest(".bjsl-overlay");
				const dropdown = overlay.querySelector(".bjsl-dropdown");
				document.querySelectorAll(".bjsl-dropdown.open").forEach((el) => {
					if (el !== dropdown) el.classList.remove("open");
				});
				dropdown.classList.add("open");
			});
			const closeLintDetails = (event) => {
				if (event.target.closest(".bjsl-overlay")) return;
				document
					.querySelectorAll(".bjsl-dropdown.open")
					.forEach((el) => el.classList.remove("open"));
			};
			document.addEventListener("click", closeLintDetails);
			eventBus.on("diagram.destroy", () => {
				document.removeEventListener("click", closeLintDetails);
			});

			// Rerun linting when drilling down/up so the panel stays relevant to current plane
			eventBus.on("root.set", () => {
				linting.update();
			});
			watchAgentConfigLint(ed.modeler);
		}
	});

	Object.assign(ed, { getLintIssues, getRawLintIssues, explainLintFinding });
}
