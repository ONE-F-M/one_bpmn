import { AiTaskSelectorProps } from "./AiTaskSelectorProps";
import { is, getBusinessObject } from "bpmn-js/lib/util/ModelUtil";

const LOW_PRIORITY = 500;

/**
 * Properties panel group for an Ad-hoc Subprocess tagged with
 * spiffworkflow:serviceType="ai_task_selector" (WI-001351).
 *
 * Shows the selector configuration: AI Provider, Model, Tool Sources and
 * the system/user prompts. The dedicated modal editor with the registry
 * tool picker is WI-001357 (3-04); this group is the inline surface.
 */
export default class AiTaskSelectorPropertiesProvider {
	constructor(propertiesPanel, translate) {
		propertiesPanel.registerProvider(LOW_PRIORITY, this);
		this.translate = translate;
	}

	getGroups(element) {
		return (groups) => {
			if (!is(element, "bpmn:AdHocSubProcess")) {
				return groups;
			}

			const bo = getBusinessObject(element);
			if ((bo.get("spiffworkflow:serviceType") ?? "") !== "ai_task_selector") {
				return groups;
			}

			groups.push({
				id: "AiTaskSelectorConfiguration",
				label: this.translate("AI Task Selector"),
				entries: AiTaskSelectorProps({ element }),
			});

			return groups;
		};
	}
}

AiTaskSelectorPropertiesProvider.$inject = ["propertiesPanel", "translate"];
