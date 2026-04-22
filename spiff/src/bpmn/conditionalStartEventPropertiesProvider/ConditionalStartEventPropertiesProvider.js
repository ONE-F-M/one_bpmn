import { ConditionalStartEventProps } from "./ConditionalStartEventProps";
import { is } from "bpmn-js/lib/util/ModelUtil";

const LOW_PRIORITY = 500;

export default class ConditionalStartEventPropertiesProvider {
	constructor(propertiesPanel, translate) {
		propertiesPanel.registerProvider(LOW_PRIORITY, this);
		this.translate = translate;
	}

	getGroups(element) {
		return (groups) => {
			if (!is(element, "bpmn:StartEvent")) {
				return groups;
			}

			const bo = element.businessObject;
			const eventDefinitions = bo.eventDefinitions || [];
			const conditionalDef = eventDefinitions.find(
				(e) => e.$type === "bpmn:ConditionalEventDefinition"
			);

			if (!conditionalDef) {
				return groups;
			}

			groups.push({
				id: "spiffworkflow-conditional-trigger-configuration",
				label: this.translate("Trigger Configuration"),
				entries: ConditionalStartEventProps({ element }),
			});

			return groups;
		};
	}
}

ConditionalStartEventPropertiesProvider.$inject = ["propertiesPanel", "translate"];
