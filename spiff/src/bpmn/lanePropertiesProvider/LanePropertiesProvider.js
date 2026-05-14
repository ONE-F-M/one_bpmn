import { LaneProps } from "./LaneProps";
import { is } from "bpmn-js/lib/util/ModelUtil";

const LOW_PRIORITY = 500;

export default class LanePropertiesProvider {
	constructor(propertiesPanel, translate) {
		propertiesPanel.registerProvider(LOW_PRIORITY, this);
		this.translate = translate;
	}

	getGroups(element) {
		return (groups) => {
			if (!is(element, "bpmn:Lane")) {
				return groups;
			}

			groups.unshift({
				id: "LaneRoleConfiguration",
				label: this.translate("Lane Role"),
				entries: LaneProps({ element }),
			});

			return groups;
		};
	}
}

LanePropertiesProvider.$inject = ["propertiesPanel", "translate"];
