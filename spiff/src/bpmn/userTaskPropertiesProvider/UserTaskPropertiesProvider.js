import { UserTaskProps } from "./UserTaskProps";
import { is } from "bpmn-js/lib/util/ModelUtil";

const LOW_PRIORITY = 500;

export default class UserTaskPropertiesProvider {
	constructor(propertiesPanel, translate) {
		propertiesPanel.registerProvider(LOW_PRIORITY, this);
		this.translate = translate;
	}

	getGroups(element) {
		return (groups) => {
			if (!is(element, "bpmn:UserTask")) {
				return groups;
			}

			groups.push({
				id: "AssigneeConfiguration",
				label: this.translate("Assignee Configuration"),
				entries: UserTaskProps({ element }),
			});

			return groups;
		};
	}
}

UserTaskPropertiesProvider.$inject = ["propertiesPanel", "translate"];
