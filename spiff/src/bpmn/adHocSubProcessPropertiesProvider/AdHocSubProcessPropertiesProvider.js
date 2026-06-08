import { AdHocSubProcessProps } from "./AdHocSubProcessProps";
import { is } from "bpmn-js/lib/util/ModelUtil";

const LOW_PRIORITY = 500;

export default class AdHocSubProcessPropertiesProvider {
	constructor(propertiesPanel, translate) {
		propertiesPanel.registerProvider(LOW_PRIORITY, this);
		this.translate = translate;
	}

	getGroups(element) {
		return (groups) => {
			if (!is(element, "bpmn:AdHocSubProcess") && !is(element, "bpmn:SubProcess")) {
				return groups;
			}

			groups.push({
				id: "AiAgentConfiguration",
				label: this.translate("AI Agent Configuration"),
				entries: AdHocSubProcessProps({ element, translate: this.translate }),
			});

			return groups;
		};
	}
}

AdHocSubProcessPropertiesProvider.$inject = ["propertiesPanel", "translate"];
