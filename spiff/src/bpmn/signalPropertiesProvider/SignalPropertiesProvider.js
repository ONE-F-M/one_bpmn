import { is } from "bpmn-js/lib/util/ModelUtil";
import { serverMessage } from "@/utils/serverMessage";
import { signalSelect } from "./SignalField";
import { signalListGroup } from "./SignalListGroup";
import { SIGNALS } from "./signalRecords";

// Runs after the library's provider (500) so its signal groups exist to be adjusted.
const LOW_PRIORITY = 400;

export default class SignalPropertiesProvider {
	constructor(propertiesPanel, translate, eventBus) {
		propertiesPanel.registerProvider(LOW_PRIORITY, this);
		this.translate = translate;
		this.eventBus = eventBus;
		this.component = signalSelect(translate);
		this.drafts = new Set();
		this.loadError = "";
	}

	getGroups(element) {
		return (groups) => {
			if (is(element, "bpmn:Process") || is(element, "bpmn:Collaboration")) {
				this.replaceSignalList(groups, element);
				return groups;
			}
			const events = element.businessObject.eventDefinitions;
			if (!events?.some((d) => is(d, "bpmn:SignalEventDefinition"))) return groups;
			const select = groups.find((g) => g.id === "signal-group")?.entries.find((e) => e.id === "signal-select");
			if (select) select.component = this.component;
			return groups;
		};
	}

	replaceSignalList(groups, element) {
		const index = groups.findIndex((g) => g.id === "signals");
		if (index < 0) return;
		if (SIGNALS.get() === null && !this.loadError) this.loadSignals(element);
		const refresh = () => this.eventBus.fire("elements.changed", { elements: [element] });
		groups[index] = signalListGroup({ element, translate: this.translate, drafts: this.drafts, loadError: this.loadError, refresh });
	}

	loadSignals(element) {
		SIGNALS.load()
			.catch((err) => {
				this.loadError = serverMessage(err);
			})
			.then(() => this.eventBus.fire("elements.changed", { elements: [element] }));
	}
}

SignalPropertiesProvider.$inject = ["propertiesPanel", "translate", "eventBus"];
