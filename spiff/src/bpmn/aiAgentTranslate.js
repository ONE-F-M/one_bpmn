import translate from "diagram-js/lib/i18n/translate/translate";
import { getBusinessObject } from "bpmn-js/lib/util/ModelUtil";

function isAiAgentTask(element) {
	const bo = element && getBusinessObject(element);
	return (
		bo?.$type === "bpmn:ServiceTask" &&
		(bo.get("spiffworkflow:serviceType") ?? "") === "ai_agent"
	);
}

// The properties-panel header asks translate("Service Task"); an AI Agent Task is a service task tagged ai_agent.
function createTranslate(injector) {
	return (template, replacements) => {
		if (template === "Service Task") {
			const selected = injector.get("selection", false)?.get();
			if (selected?.length === 1 && isAiAgentTask(selected[0])) {
				return translate("AI Agent Task", replacements);
			}
		}
		return translate(template, replacements);
	};
}

createTranslate.$inject = ["injector"];

export default { translate: ["factory", createTranslate] };
