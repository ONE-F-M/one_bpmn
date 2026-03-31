import { IntermediateEventProps } from "./IntermediateEventProps";
import { is } from "bpmn-js/lib/util/ModelUtil";

const LOW_PRIORITY = 500;

export default class IntermediateEventPropertiesProvider {
	constructor(propertiesPanel, translate) {
		propertiesPanel.registerProvider(LOW_PRIORITY, this);
		this.translate = translate;
	}

	getGroups(element) {
		return (groups) => {
			if (!is(element, "bpmn:IntermediateCatchEvent") && !is(element, "bpmn:IntermediateThrowEvent")) {
				return groups;
			}

			groups.push({
				id: "IntermediateEventConfiguration",
				label: this.translate("Event Configuration"),
				entries: IntermediateEventProps({ element }),
			});

			return groups;
		};
	}
}

IntermediateEventPropertiesProvider.$inject = ["propertiesPanel", "translate"];
