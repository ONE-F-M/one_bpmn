import { AiAgentProps } from "./AiAgentProps";
import { is, getBusinessObject } from "bpmn-js/lib/util/ModelUtil";

const LOW_PRIORITY = 500;

/**
 * Dedicated properties panel provider for AI Agent Tasks.
 *
 * An AI Agent Task is a bpmn:ServiceTask tagged with
 * spiffworkflow:serviceType="ai_agent" (created via the Change element menu).
 * This provider shows its own "AI Agent Task" group instead of the generic
 * Service Configuration group, which is suppressed for these elements in
 * ServiceTaskPropertiesProvider.
 */
export default class AiAgentPropertiesProvider {
	constructor(propertiesPanel, translate) {
		propertiesPanel.registerProvider(LOW_PRIORITY, this);
		this.translate = translate;
	}

	getGroups(element) {
		return (groups) => {
			if (!is(element, "bpmn:ServiceTask")) {
				return groups;
			}

			const bo = getBusinessObject(element);
			if ((bo.get("spiffworkflow:serviceType") ?? "") !== "ai_agent") {
				return groups;
			}

			groups.push({
				id: "AIAgentConfiguration",
				label: this.translate("AI Agent Task"),
				entries: AiAgentProps({ element }),
			});

			return groups;
		};
	}
}

AiAgentPropertiesProvider.$inject = ["propertiesPanel", "translate"];
