import { ServiceTaskProps } from "./ServiceTaskProps";
import { is } from "bpmn-js/lib/util/ModelUtil";

const LOW_PRIORITY = 500;

export default class ServiceTaskPropertiesProvider {
	constructor(propertiesPanel, translate) {
		propertiesPanel.registerProvider(LOW_PRIORITY, this);
		this.translate = translate;
	}

	getGroups(element) {
		return (groups) => {
			if (!is(element, "bpmn:ServiceTask")) {
				return groups;
			}

			groups.push({
				id: "ServiceConfiguration",
				label: this.translate("Service Configuration"),
				entries: ServiceTaskProps({ element }),
			});

			return groups;
		};
	}
}

ServiceTaskPropertiesProvider.$inject = ["propertiesPanel", "translate"];
