import { StartEventProps } from "./StartEventProps";
import { is } from "bpmn-js/lib/util/ModelUtil";

const LOW_PRIORITY = 500;

export default class StartEventPropertiesProvider {
	constructor(propertiesPanel, translate) {
		propertiesPanel.registerProvider(LOW_PRIORITY, this);
		this.translate = translate;
	}

	getGroups(element) {
		return (groups) => {
			// Only apply to a plain StartEvent with no event definitions
			// (not Timer, Message, Signal, etc.)
			if (!is(element, "bpmn:StartEvent")) {
				return groups;
			}

			const bo = element.businessObject;
			const eventDefinitions = bo.eventDefinitions || [];

			if (eventDefinitions.length > 0) {
				// Has a timer / message / etc. event definition — skip
				return groups;
			}

			groups.push({
				id: "TriggerConfiguration",
				label: this.translate("Trigger Configuration"),
				entries: StartEventProps({ element }),
			});

			return groups;
		};
	}
}

StartEventPropertiesProvider.$inject = ["propertiesPanel", "translate"];
