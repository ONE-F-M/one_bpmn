import { UserTaskProps } from "./UserTaskProps";
import { NotificationProps } from "./NotificationProps";
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
				label: this.translate("Assignment Configuration"),
				entries: UserTaskProps({ element }),
			});

			groups.push({
				id: "NotificationConfiguration",
				label: this.translate("Notification Configuration"),
				entries: NotificationProps({ element }),
			});

			return groups;
		};
	}
}

UserTaskPropertiesProvider.$inject = ["propertiesPanel", "translate"];
