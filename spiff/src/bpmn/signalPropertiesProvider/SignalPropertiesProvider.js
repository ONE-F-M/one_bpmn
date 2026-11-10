import { is } from "bpmn-js/lib/util/ModelUtil";
import { serverMessage } from "@/utils/serverMessage";
import { makeProvider } from "../shared/makePropertiesProvider";
import { signalSelect } from "./SignalField";
import { signalListGroup } from "./SignalListGroup";
import { SIGNALS } from "./signalRecords";

// Runs after the library's provider (500) so its signal groups exist to be adjusted.
const SIGNAL_PRIORITY = 400;

function setup({ translate, eventBus }) {
	return { translate, eventBus, component: signalSelect(translate), drafts: new Set(), loadError: "" };
}

function editSignalGroups({ groups, element, state }) {
	if (is(element, "bpmn:Process") || is(element, "bpmn:Collaboration")) {
		replaceSignalList(groups, element, state);
		return;
	}
	const events = element.businessObject.eventDefinitions;
	if (!events?.some((d) => is(d, "bpmn:SignalEventDefinition"))) return;
	const select = groups.find((g) => g.id === "signal-group")?.entries.find((e) => e.id === "signal-select");
	if (select) select.component = state.component;
}

function replaceSignalList(groups, element, state) {
	const index = groups.findIndex((g) => g.id === "signals");
	if (index < 0) return;
	if (SIGNALS.get() === null && !state.loadError) loadSignals(element, state);
	const refresh = () => state.eventBus.fire("elements.changed", { elements: [element] });
	groups[index] = signalListGroup({
		element,
		translate: state.translate,
		drafts: state.drafts,
		loadError: state.loadError,
		refresh,
	});
}

function loadSignals(element, state) {
	SIGNALS.load()
		.catch((err) => {
			state.loadError = serverMessage(err);
		})
		.then(() => state.eventBus.fire("elements.changed", { elements: [element] }));
}

export default {
	__init__: ["bpmnSignalMasterPropertiesProvider"],
	bpmnSignalMasterPropertiesProvider: [
		"type",
		makeProvider(["bpmn:Process", "bpmn:Collaboration", "bpmn:Event"], null, null, null, {
			priority: SIGNAL_PRIORITY,
			inject: ["eventBus"],
			setup,
			edit: editSignalGroups,
		}),
	],
};
