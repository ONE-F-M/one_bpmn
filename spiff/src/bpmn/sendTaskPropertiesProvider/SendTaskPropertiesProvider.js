import { SendTaskProps } from "./SendTaskProps";
import { is } from "bpmn-js/lib/util/ModelUtil";

const LOW_PRIORITY = 500;

export default class SendTaskPropertiesProvider {
	constructor(propertiesPanel, translate) {
		propertiesPanel.registerProvider(LOW_PRIORITY, this);
		this.translate = translate;
	}

	getGroups(element) {
		return (groups) => {
			if (!is(element, "bpmn:SendTask")) {
				return groups;
			}

			groups.push({
				id: "NotificationConfiguration",
				label: this.translate("Notification Configuration"),
				entries: SendTaskProps({ element }),
			});

			return groups;
		};
	}
}

SendTaskPropertiesProvider.$inject = ["propertiesPanel", "translate"];
