/**
 * i18n module for bpmn-js integration.
 *
 * This module exports the custom translate function wrapped in
 * the format expected by bpmn-js additionalModules.
 *
 * The translate service is made selection-aware so the properties-panel header
 * can show "AI Agent Task" for AI Agent Tasks. An AI Agent Task is a
 * bpmn:ServiceTask tagged spiffworkflow:serviceType="ai_agent", so the stock
 * header would otherwise render "Service Task". Remapping at the translate
 * layer makes the panel render the correct label natively — no DOM patching,
 * and no fighting the properties-panel virtual DOM.
 */

import customTranslate from "./customTranslate";
import { getBusinessObject } from "bpmn-js/lib/util/ModelUtil";

function isAiAgentTask(element) {
	const bo = element && getBusinessObject(element);
	return (
		bo &&
		bo.$type === "bpmn:ServiceTask" &&
		(bo.get("spiffworkflow:serviceType") ?? "") === "ai_agent"
	);
}

// Factory: returns the translate function. The injector is resolved lazily at
// call time (via injector.get) so there is no module init-order coupling.
function createTranslate(injector) {
	return function translate(template, replacements) {
		// The header type label for a Service Task is translate("Service Task").
		// When the single selected element is an AI Agent Task, relabel it.
		if (template === "Service Task") {
			const selection = injector.get("selection", false);
			const selected = selection && selection.get();
			if (selected && selected.length === 1 && isAiAgentTask(selected[0])) {
				return customTranslate("AI Agent Task", replacements);
			}
		}
		return customTranslate(template, replacements);
	};
}

createTranslate.$inject = ["injector"];

export default {
	translate: ["factory", createTranslate],
};
