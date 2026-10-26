import { is } from "bpmn-js/lib/util/ModelUtil";
import { signalSelect } from "./SignalField";

// Runs after the library's provider (500) so its signal group exists to be adjusted.
const LOW_PRIORITY = 400;

export default class SignalPropertiesProvider {
	constructor(propertiesPanel, translate) {
		propertiesPanel.registerProvider(LOW_PRIORITY, this);
		this.component = signalSelect(translate);
	}

	getGroups(element) {
		return (groups) => {
			const events = element.businessObject.eventDefinitions;
			if (!events?.some((d) => is(d, "bpmn:SignalEventDefinition"))) return groups;
			const select = groups.find((g) => g.id === "signal-group")?.entries.find((e) => e.id === "signal-select");
			if (select) select.component = this.component;
			return groups;
		};
	}
}

SignalPropertiesProvider.$inject = ["propertiesPanel", "translate"];
